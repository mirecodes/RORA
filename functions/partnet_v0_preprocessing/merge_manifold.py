import os
import sys

import numpy as np
import trimesh
import manifold3d as m3d
from yourdfpy import URDF

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from functions.lib.config import load_cfg

INPUT_DIR = os.path.join(ROOT, "data", "preprocess", "partnet_v0")   # <name>/mobility.urdf
OUTPUT_DIR = os.path.join(ROOT, "data", "objects")                   # <name>/mesh_fused.ply


def merge_urdf_manifold_ply(urdf_path, joint_cfg, output_path="fused_mesh.ply"):
    print(f"[Info] Loading URDF: {urdf_path}")
    robot = URDF.load(urdf_path)

    # 1. Apply joint configuration
    valid_cfg = {k: v for k, v in joint_cfg.items() if k in robot.actuated_joint_names}
    robot.update_cfg(configuration=valid_cfg)

    # 2. Get scene
    scene = robot.scene

    manifolds = []

    for name, node in scene.geometry.items():
        transform = scene.graph.get(name)[0]
        mesh = node.copy()
        mesh.apply_transform(transform)

        try:
            # Watertight check and repair
            if not mesh.is_watertight:
                # print(f"[Warning] '{name}' not watertight, filling holes.")
                mesh.fill_holes()
                if not mesh.is_watertight:
                    print(f"  -> '{name}' repair failed. Using convex hull.")
                    mesh = mesh.convex_hull

            # Validity check
            if mesh.is_empty:
                print(f"  -> [Skip] '{name}' mesh is empty (is_empty).")
                continue
            
            if len(mesh.vertices) < 3 or len(mesh.faces) < 1:
                print(f"  -> [Skip] '{name}' too few elements (V={len(mesh.vertices)}, F={len(mesh.faces)}).")
                continue

            # --- Trimesh -> Manifold ---
            verts = np.array(mesh.vertices, dtype=np.float32)
            faces = np.array(mesh.faces, dtype=np.int32)
            
            m_mesh = m3d.Mesh(vert_properties=verts, tri_verts=faces)
            m_obj = m3d.Manifold(m_mesh)
            
            if m_obj.num_vert() == 0:
                print(f"  -> [Skip] '{name}' Manifold conversion is empty.")
                continue

            manifolds.append(m_obj)
            # ------------------------------------------------

        except Exception as e:
            print(f"[Error] '{name}' conversion failed: {e}")

    if not manifolds:
        print("[Error] No valid meshes to merge.")
        return None

    print(f"[Info] Boolean union of {len(manifolds)} parts...")

    # 3. Boolean union
    combined_manifold = manifolds[0]
    for i in range(1, len(manifolds)):
        try:
            combined_manifold += manifolds[i]
        except Exception as e:
            print(f"[Warning] Merge error (index {i}): {e}")

    if combined_manifold.num_vert() == 0:
        print("[Error] Merged result is empty (Vertices=0).")
        return None

    # 4. Convert result for PLY export
    out_mesh = combined_manifold.to_mesh()
    final_trimesh = trimesh.Trimesh(
        vertices=np.array(out_mesh.vert_properties),
        faces=np.array(out_mesh.tri_verts)
    )

    # [Important] Recompute normals for PLY output (smooth shading)
    final_trimesh.fix_normals()

    if final_trimesh.is_watertight:
        print("[Success] Watertight mesh created.")
    else:
        print(f"[Warning] Result mesh is not watertight. (V={len(final_trimesh.vertices)}, F={len(final_trimesh.faces)})")

    if final_trimesh.is_empty:
         print("[Error] Final trimesh is empty.")
         return None

    # Export PLY (binary is smaller; use ascii to read as text)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    final_trimesh.export(output_path, file_type='ply', encoding='binary')
    print(f"[Info] Saved: {output_path}")
    return final_trimesh


if __name__ == "__main__":
    # Settings: cfgs/partnet_v0_preprocessing/partnet_v0_preprocessing_cfg.yml
    cfg = load_cfg("partnet_v0_preprocessing/partnet_v0_preprocessing_cfg")
    objects = cfg["objects"]

    for object_name in cfg["targets"]:
        if object_name not in objects:
            print(f"[Skip] '{object_name}' not found in cfg objects: {list(objects)}")
            continue

        urdf_path = os.path.join(INPUT_DIR, object_name, "mobility.urdf")
        output_path = os.path.join(OUTPUT_DIR, object_name, "mesh_fused.ply")
        joint_cfg = (objects[object_name] or {}).get("joint_offset") or {}

        if os.path.exists(urdf_path):
            merge_urdf_manifold_ply(urdf_path, joint_cfg, output_path)
        else:
            print(f"[Error] URDF file not found: {urdf_path}")
