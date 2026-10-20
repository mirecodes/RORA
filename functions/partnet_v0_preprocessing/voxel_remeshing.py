import os
import sys

import numpy as np
import trimesh
from yourdfpy import URDF

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from functions.utils.config import load_cfg

INPUT_DIR = os.path.join(ROOT, "data", "preprocess", "partnet_v0")   # <name>/mobility.urdf
OUTPUT_DIR = os.path.join(ROOT, "data", "objects")                   # <name>/mesh.ply (pipeline input)


def merge_urdf_voxel_ply(urdf_path, joint_cfg, output_path="fused_voxel.ply", voxel_pitch=0.005, rotation_deg=0.0):
    print(f"[Info] Loading URDF: {urdf_path}")
    robot = URDF.load(urdf_path)

    # 1. Apply configuration (deg -> rad)
    joint_cfg_rad = {k: np.deg2rad(float(v)) for k, v in joint_cfg.items()}
    valid_cfg = {k: v for k, v in joint_cfg_rad.items() if k in robot.actuated_joint_names}
    robot.update_cfg(configuration=valid_cfg)


    # 2. Get scene
    scene = robot.scene
    all_meshes = []

    for name, node in scene.geometry.items():
        transform = scene.graph.get(name)[0]
        mesh = node.copy()
        mesh.apply_transform(transform)
        all_meshes.append(mesh)

    if not all_meshes:
        print("[Error] No meshes to merge.")
        return None

    print("[Info] Concatenating meshes...")
    combined_raw = trimesh.util.concatenate(all_meshes)
    
    # 2.5 Apply Rotation (around Z-axis, at origin)
    if rotation_deg != 0:
        print(f"[Info] Rotating {rotation_deg} deg (Z-axis)...")
        angle_rad = np.deg2rad(rotation_deg)
        rot_matrix = trimesh.transformations.rotation_matrix(angle_rad, [0, 0, 1])
        combined_raw.apply_transform(rot_matrix)

    # Save raw bounds/center (to verify restoration later)
    raw_bounds = combined_raw.bounds
    raw_center = combined_raw.centroid
    print(f"[Debug] Raw Mesh Bounds: {raw_bounds}")
    print(f"[Debug] Raw Mesh Center: {raw_center}")

    # 3. Voxelization & Remeshing
    print(f"[Info] Voxelizing and remeshing (Pitch: {voxel_pitch}m)...")

    try:
        # Voxelization with filling
        # voxelized() builds a local grid from the mesh bounding box,
        # so the grid origin is near mesh.bounds[0], not (0,0,0).
        voxel_grid = combined_raw.voxelized(pitch=voxel_pitch)
        voxel_grid.fill() 
        
        # Remesh via Marching Cubes
        final_mesh = voxel_grid.marching_cubes

        # [Fix] Restore coordinates (Origin & Scale)
        # voxel_grid.transform maps index -> world coords,
        # including both scale (pitch) and translation (origin).
        matrix = voxel_grid.transform
        grid_origin = matrix[:3, 3]
        print(f"[Debug] Voxel Grid Origin (Translation): {grid_origin}")
        
        # Check current mesh scale
        current_size = final_mesh.extents
        raw_size = raw_bounds[1] - raw_bounds[0]
        ratio = np.mean(current_size / (raw_size + 1e-9))
        print(f"[Debug] Mesh/Raw Size Ratio: {ratio:.2f}")

        if ratio > 10.0:
            # marching_cubes output is in index coords (integers):
            # apply the full transform to restore scale and origin.
            print("[Info] Index coords detected -> applying full transform")
            final_mesh.apply_transform(matrix)
        else:
            # marching_cubes output is already scaled (meters) but
            # positioned locally (around 0,0,0): translate by grid origin.

            # Offset from raw position
            dist = np.linalg.norm(final_mesh.centroid - raw_center)
            if dist > voxel_pitch:
                print(f"[Info] Translating by Grid Origin({grid_origin}) to correct position.")
                final_mesh.apply_translation(grid_origin)
            else:
                print("[Info] Position already matches raw mesh.")

        # Final check after correction
        final_center_fixed = final_mesh.centroid
        print(f"[Debug] Fixed Mesh Center: {final_center_fixed}")
        
        # Laplacian smoothing
        trimesh.smoothing.filter_laplacian(final_mesh, iterations=2)

        # [Important] Compute normals for PLY output
        final_mesh.fix_normals()

        if final_mesh.is_watertight:
            print("[Success] Watertight mesh created.")
        else:
            print(f"[Warning] Result mesh is not watertight. (V={len(final_mesh.vertices)}, F={len(final_mesh.faces)})")

        # Export PLY
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        final_mesh.export(output_path, file_type='ply', encoding='binary')
        print(f"[Info] Saved: {output_path}")
        return final_mesh

    except Exception as e:
        print(f"[Error] Voxelization failed: {e}")
        return None


if __name__ == "__main__":
    # Settings: cfgs/partnet_v0_preprocessing/partnet_v0_preprocessing_cfg.yml
    cfg = load_cfg("partnet_v0_preprocessing/partnet_v0_preprocessing_cfg")
    objects, voxel = cfg["objects"], cfg["voxel"]

    for object_name in cfg["targets"]:
        print(f"\n{'='*50}")
        print(f"[Info] Processing: {object_name}")
        print(f"{'='*50}")

        if object_name not in objects:
            print(f"[Skip] '{object_name}' not found in cfg objects: {list(objects)}")
            continue

        urdf_path = os.path.join(INPUT_DIR, object_name, "mobility.urdf")
        output_path = os.path.join(OUTPUT_DIR, object_name, "mesh.ply")
        joint_cfg = (objects[object_name] or {}).get("joint_offset") or {}

        if os.path.exists(urdf_path):
            merge_urdf_voxel_ply(urdf_path, joint_cfg, output_path,
                                 voxel_pitch=voxel["pitch"], rotation_deg=voxel["rotation_deg"])
        else:
            print(f"[Error] URDF file not found: {urdf_path}")
