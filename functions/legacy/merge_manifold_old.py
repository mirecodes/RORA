import numpy as np
import trimesh
import manifold3d as m3d
from yourdfpy import URDF
import os


def merge_urdf_manifold_ply(urdf_path, joint_cfg, output_path="fused_mesh.ply"):
    print(f"[Info] Loading URDF: {urdf_path}")
    robot = URDF.load(urdf_path)

    # 1. Apply joint configuration
    valid_cfg = {k: v for k, v in joint_cfg.items() if k in robot.actuated_joint_names}
    robot.update_cfg(configuration=valid_cfg)

    # 2. Get scene (revised logic)
    scene = robot.scene

    manifolds = []

    for name, node in scene.geometry.items():
        transform = scene.graph.get(name)[0]
        mesh = node.copy()
        mesh.apply_transform(transform)

        try:
            # Watertight check and repair
            if not mesh.is_watertight:
                # print(f"[Warning] '{name}' not closed; filling holes.")
                mesh.fill_holes()
                if not mesh.is_watertight:
                    print(f"  -> '{name}' repair failed. Using convex hull.")
                    mesh = mesh.convex_hull

            # --- Trimesh -> Manifold (revised logic) ---
            verts = np.array(mesh.vertices, dtype=np.float32)
            faces = np.array(mesh.faces, dtype=np.int32)
            m_mesh = m3d.Mesh(vert_properties=verts, tri_verts=faces)
            m_obj = m3d.Manifold(m_mesh)
            manifolds.append(m_obj)
            # ------------------------------------------------

        except Exception as e:
            print(f"[Error] '{name}' conversion failed: {e}")

    if not manifolds:
        print("[Error] No meshes to merge.")
        return None

    print(f"[Info] Boolean-union of {len(manifolds)} parts...")

    # 3. Boolean union
    combined_manifold = manifolds[0]
    for i in range(1, len(manifolds)):
        combined_manifold += manifolds[i]

    # 4. Convert result and save PLY
    out_mesh = combined_manifold.to_mesh()
    final_trimesh = trimesh.Trimesh(
        vertices=np.array(out_mesh.vert_properties),
        faces=np.array(out_mesh.tri_verts)
    )

    # [Important] Recompute normals for PLY (smooth shading)
    final_trimesh.fix_normals()

    if final_trimesh.is_watertight:
        print("[Success] Watertight mesh created.")

    # Export PLY (binary = smaller; use ascii for readable text)
    final_trimesh.export(output_path, file_type='ply', encoding='binary')
    print(f"[Info] Saved: {output_path}")
    return final_trimesh


if __name__ == "__main__":
    my_urdf = "urdf/toilet/mobility.urdf"

    # Test config (tweak as needed)
    my_config = {
        'joint_0': 0,
        'joint_1': np.pi / 3,
        'joint_2': np.pi / 6,
        'joint_3': 0.0,
    }

    if os.path.exists(my_urdf):
        merge_urdf_manifold_ply(my_urdf, my_config)
    else:
        print(f"File not found: {my_urdf}")