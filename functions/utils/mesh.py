import os

import coacd
import manifold3d
import numpy as np
import pymeshlab
import trimesh
from shapely.geometry import Polygon

from functions.math.geometry import pca_plane, ransac_plane, rotmat
from functions.math.graph import mesh_boundary_cycles


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


def _largest_cycle(t_mesh: trimesh.Trimesh):
    cycles = mesh_boundary_cycles(t_mesh)
    return max(cycles, key=len) if cycles else None


def align_transform(ms: pymeshlab.MeshSet):
    """4x4 transform putting the mesh bottom (largest boundary cycle, else RANSAC plane) on z=0, z-up."""
    t_mesh = to_trimesh(ms)
    cycle = _largest_cycle(t_mesh)
    if cycle is not None:
        bottom = t_mesh.vertices[cycle]
    else:
        print("[warning] Boundary cycle does not exist. Trying to find the largest plane using RANSAC...")
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
    """Move the largest boundary cycle onto z = target_z."""
    t_mesh = to_trimesh(ms)
    cycle = _largest_cycle(t_mesh)
    if cycle is None:
        print("[warning] Boundary cycle does not exist. Nothing to flatten.")
        return ms
    t_mesh.vertices[cycle, 2] = target_z
    return replace_first_mesh(ms, t_mesh.vertices, t_mesh.faces)


def fill_bottom_hole(ms: pymeshlab.MeshSet) -> pymeshlab.MeshSet:
    """Cap the largest boundary cycle (assumed flat on z=0) with a constrained Delaunay patch."""
    t_mesh = to_trimesh(ms)
    cycle = _largest_cycle(t_mesh)
    if cycle is None:
        print("[warning] Boundary cycle does not exist. Nothing to fill.")
        return ms
    cap_xy, cap_faces = trimesh.creation.triangulate_polygon(Polygon(t_mesh.vertices[cycle][:, :2]))
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


def close_link(verts, faces, close_holes: dict, coacd_params: dict) -> trimesh.Trimesh:
    """Watertight link: pymeshlab hole closing, else the union of the link's own CoACD convex parts."""
    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(vertex_matrix=verts, face_matrix=faces))
    ms.meshing_close_holes(**close_holes)
    closed = to_trimesh(ms)
    if closed.is_watertight:
        return closed
    print("[warn] Hole closing left the link open; using the union of its CoACD convex parts instead.")
    # preprocess must stay off: its manifold remesh turns an open link into a thin shell (box volume 1 -> 0.18)
    hulls = coacd.run_coacd(coacd.Mesh(verts, faces), **{**coacd_params, "preprocess_mode": "off"})
    union = manifold3d.Manifold.batch_boolean(
        [manifold3d.Manifold(manifold3d.Mesh(vert_properties=np.asarray(v, np.float32),
                                             tri_verts=np.asarray(f, np.uint32))) for v, f in hulls],
        manifold3d.OpType.Add).to_mesh()
    return trimesh.Trimesh(vertices=union.vert_properties[:, :3], faces=union.tri_verts)


def save_link_meshes(verts, faces, labels, parts_num: int, out_dir: str,
                     close_holes: dict, coacd_params: dict) -> dict[str, str]:
    """Save out_dir/link_<k>.ply per label k, closed by close_link. Returns {str(k): path}."""
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for k in range(1, parts_num + 1):
        sv, sf = submesh(verts, faces, labels, k)
        if sv is not None:
            paths[str(k)] = os.path.join(out_dir, f"link_{k}.ply")
            close_link(sv, sf, close_holes, coacd_params).export(paths[str(k)])
    return paths
