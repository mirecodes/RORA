import os

import numpy as np
import pymeshlab
import trimesh
from shapely.geometry import Polygon

from functions.math.geometry import pca_plane, ransac_plane, rotmat
from functions.math.graph import mesh_boundary_loops


# =============================================================================
# pymeshlab MeshSet helpers
# =============================================================================
def repair_mesh(ms: pymeshlab.MeshSet):
    ms.meshing_remove_duplicate_vertices()
    ms.meshing_remove_duplicate_faces()
    ms.meshing_remove_unreferenced_vertices()
    ms.meshing_merge_close_vertices()  # may cause problem
    ms.meshing_repair_non_manifold_edges(method=0)
    ms.meshing_repair_non_manifold_vertices()
    return ms


def to_trimesh(ms: pymeshlab.MeshSet) -> trimesh.Trimesh:
    m = ms.current_mesh()
    return trimesh.Trimesh(vertices=m.vertex_matrix(), faces=m.face_matrix())


def replace_first_mesh(ms: pymeshlab.MeshSet, verts, faces) -> pymeshlab.MeshSet:
    """New MeshSet with mesh 0 replaced by (verts, faces); other meshes kept."""
    out = pymeshlab.MeshSet()
    out.add_mesh(pymeshlab.Mesh(vertex_matrix=verts, face_matrix=faces))
    for i in range(1, ms.mesh_number()):
        out.add_mesh(ms.mesh(i))
    return out


def _largest_loop(t_mesh: trimesh.Trimesh):
    loops = mesh_boundary_loops(t_mesh)
    return max(loops, key=len) if loops else None


def align_transform(ms: pymeshlab.MeshSet):
    """4x4 transform putting the mesh bottom (largest boundary loop, else RANSAC plane) on z=0, z-up."""
    t_mesh = to_trimesh(ms)
    loop = _largest_loop(t_mesh)
    if loop is not None:
        bottom = t_mesh.vertices[loop]
    else:
        print("[warning] Boundary loop does not exist. Trying to find the largest plane using RANSAC...")
        threshold = 0.005 * np.linalg.norm(t_mesh.bounds[1] - t_mesh.bounds[0])  # 0.5% of the diagonal
        inliers = ransac_plane(t_mesh.vertices, threshold=threshold)
        if inliers.sum() < 3:
            print("[error] RANSAC failed to find a valid plane.")
            return None
        bottom = t_mesh.vertices[inliers]
        print(f"[info] RANSAC found plane with {len(bottom)} inliers.")

    # Bottom normal pointing away from the body, rotated onto +z
    center, normal = pca_plane(bottom)
    if np.dot(normal, center - t_mesh.centroid) > 0:
        normal = -normal
    z = np.array([0.0, 0.0, 1.0])
    axis = np.cross(normal, z)
    s, c = np.linalg.norm(axis), np.dot(normal, z)
    R = (np.eye(3) if c > 0 else -np.eye(3)) if np.isclose(s, 0) else rotmat(axis, np.arctan2(s, c))

    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = -(bottom @ R.T).mean(axis=0)  # translate after rotating
    return T


def flatten_bottom_hole(ms: pymeshlab.MeshSet, target_z: float = 0.0) -> pymeshlab.MeshSet:
    """Move the largest boundary loop onto z = target_z."""
    t_mesh = to_trimesh(ms)
    loop = _largest_loop(t_mesh)
    if loop is None:
        print("[warning] Boundary loop does not exist. Nothing to flatten.")
        return ms
    t_mesh.vertices[loop, 2] = target_z
    return replace_first_mesh(ms, t_mesh.vertices, t_mesh.faces)


def fill_bottom_hole(ms: pymeshlab.MeshSet) -> pymeshlab.MeshSet:
    """Cap the largest boundary loop (assumed flat on z=0) with a constrained Delaunay patch."""
    t_mesh = to_trimesh(ms)
    loop = _largest_loop(t_mesh)
    if loop is None:
        print("[warning] Boundary loop does not exist. Nothing to fill.")
        return ms
    cap_xy, cap_faces = trimesh.creation.triangulate_polygon(Polygon(t_mesh.vertices[loop][:, :2]))
    cap = np.column_stack([cap_xy, np.zeros(len(cap_xy))])
    offset = len(t_mesh.vertices)
    t_mesh.vertices = np.vstack([t_mesh.vertices, cap])
    t_mesh.faces = np.vstack([t_mesh.faces, cap_faces + offset])
    t_mesh.merge_vertices()
    return replace_first_mesh(ms, t_mesh.vertices, t_mesh.faces)


# =============================================================================
# Link meshes (trimesh, on disk)
# =============================================================================
def submesh(verts: np.ndarray, faces: np.ndarray, labels: np.ndarray, k: int):
    """(verts, faces) of the faces whose 3 vertices all have label k, or (None, None)."""
    faces_k = faces[np.all(labels[faces] == k, axis=1)]
    if faces_k.size == 0:
        return None, None
    vidx = np.unique(faces_k.ravel())
    vmap = -np.ones(labels.shape[0], dtype=int)
    vmap[vidx] = np.arange(vidx.size)
    return verts[vidx], vmap[faces_k]


def save_link_meshes(verts, faces, labels, categories_num: int, out_dir: str) -> dict[str, str]:
    """Save out_dir/link_<k>.ply per label k. Returns {str(k): path}."""
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for k in range(1, categories_num + 1):
        sv, sf = submesh(verts, faces, labels, k)
        if sv is not None:
            paths[str(k)] = os.path.join(out_dir, f"link_{k}.ply")
            trimesh.Trimesh(vertices=sv, faces=sf, process=False).export(paths[str(k)])
    return paths


def append_patches(mesh_paths: dict[str, str], patch_vertices: dict, patch_faces: dict) -> None:
    """Append patches {k: [(P, F), ...]} to the link mesh files in place."""
    for k_str, path in mesh_paths.items():
        k = int(k_str)
        if not patch_vertices.get(k):
            continue
        tm = trimesh.load(path, process=False)
        V, F = tm.vertices, tm.faces
        for P, Ft in zip(patch_vertices[k], patch_faces[k]):
            if P.size and Ft.size:
                F = np.vstack([F, Ft + len(V)])
                V = np.vstack([V, P])
        out = trimesh.Trimesh(vertices=V, faces=F, process=False)
        out.update_faces(out.unique_faces() & out.nondegenerate_faces())
        out.remove_unreferenced_vertices()
        out.export(path)
