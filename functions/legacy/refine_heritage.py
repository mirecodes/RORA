from dataclasses import dataclass, field
import pymeshlab
import os
import numpy as np
import trimesh
from sklearn.decomposition import PCA
from collections import defaultdict
import open3d as o3d
from scipy.spatial.transform import Rotation as R  # for rotation conversion
from scipy.spatial import Delaunay


@dataclass
class MeshRefinementConfig:
    # --------------------------------------------------------------------------
    # 1. Basic settings (user-editable)
    # --------------------------------------------------------------------------
    # I/O paths relative to project root
    mesh_in_path: str = "data/meshes/bonsai_pot.ply"
    mesh_out_path: str = "out/meshes/refined_bonsai_pot.obj"
    mesh_dev_path: str = "out/meshes/processed_bonsai_pot.obj"

    # Feature flags
    automatic_alignment: bool = True  # True: auto-align bottom via PCA at start
    step_by_step_visualization: bool = True  # True: visualize each step

    # --- [Added] initial cleanup params ---
    # Remove pieces smaller than this % of the main mesh diagonal.
    # e.g. 1.0 removes all isolated pieces under 1%.
    initial_cleanup_threshold: float = 1.0

    # --------------------------------------------------------------------------
    # 2. Derived paths (do not edit)
    # --------------------------------------------------------------------------
    root_dir: str = field(default_factory=os.getcwd, init=False)
    mesh_in_dir: str = field(init=False)
    mesh_out_dir: str = field(init=False)
    mesh_dev_dir: str = field(init=False)

    def __post_init__(self):
        self.mesh_in_dir = os.path.abspath(os.path.join(self.root_dir, "..", self.mesh_in_path))
        self.mesh_out_dir = os.path.abspath(os.path.join(self.root_dir, "..", self.mesh_out_path))
        self.mesh_dev_dir = os.path.abspath(os.path.join(self.root_dir, "..", self.mesh_dev_path))


# ============================================================================
# Loop finding and auto-alignment (final verified version)
# ============================================================================

def find_boundary_loops(t_mesh):
    # (kept identical to provided code)
    edges = t_mesh.edges_sorted
    unique_edges, inverse, counts = np.unique(edges, axis=0, return_inverse=True, return_counts=True)
    boundary_edges = unique_edges[counts == 1]
    if len(boundary_edges) == 0:
        return []
    neighbours = defaultdict(list)
    for v1, v2 in boundary_edges:
        neighbours[v1].append(v2)
        neighbours[v2].append(v1)
    loops = []
    remaining_edges = set(map(tuple, boundary_edges))
    while remaining_edges:
        v_start, v_next = remaining_edges.pop()
        current_loop = [v_start, v_next]
        while v_next != v_start:
            v_prev = current_loop[-2]
            options = neighbours[v_next]
            if len(options) != 2:
                break
            if options[0] == v_prev:
                v_next = options[1]
            else:
                v_next = options[0]
            if v_next == v_start:
                break
            current_loop.append(v_next)
        for i in range(len(current_loop) - 1):
            remaining_edges.discard(tuple(sorted((current_loop[i], current_loop[i + 1]))))
        remaining_edges.discard(tuple(sorted((current_loop[-1], current_loop[0]))))
        loops.append(current_loop)
    return loops


def calculate_transforms(ms):
    # (kept identical to provided code)
    print("Computing alignment transform from original mesh...")
    current_mesh = ms.current_mesh()
    t_mesh = trimesh.Trimesh(vertices=current_mesh.vertex_matrix(), faces=current_mesh.face_matrix())
    loops_indices = find_boundary_loops(t_mesh)
    if not loops_indices:
        print("Warning: no boundary loop; cannot compute transform.")
        return None, None

    print(f"# loops: {len(loops_indices)}")
    largest_loop_indices = max(loops_indices, key=len)
    loop_verts = t_mesh.vertices[largest_loop_indices]

    pca = PCA(n_components=3)
    pca.fit(loop_verts)
    plane_normal = pca.components_[2]
    if np.dot(plane_normal, loop_verts.mean(axis=0) - t_mesh.centroid) < 0:
        plane_normal *= -1

    # --- Replaced with user-provided, verified code ---
    target_normal = np.array([0., 0., 1.])
    v = np.cross(plane_normal, target_normal)
    s = np.linalg.norm(v)
    c = np.dot(plane_normal, target_normal)

    if np.isclose(s, 0):
        rotation_matrix = np.eye(3) if c > 0 else -np.eye(3)
    else:
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        rotation_matrix = np.eye(3) + vx + vx.dot(vx) * ((1 - c) / (s ** 2))
    # --- End replacement ---

    # Rotate virtually to get Z offset
    rotated_loop_verts = loop_verts @ rotation_matrix.T
    z_mean = rotated_loop_verts[:, 2].mean()

    # Forward transform (rotation + translation)
    translation_matrix = np.eye(4)
    translation_matrix[2, 3] = z_mean

    rotation_4x4 = np.eye(4)
    rotation_4x4[:3, :3] = rotation_matrix

    forward_transform = translation_matrix @ rotation_4x4

    inverse_transform = np.linalg.inv(forward_transform)

    print("Forward and inverse transforms computed.")
    return forward_transform, inverse_transform


def apply_transform_from_matrix(ms, matrix_4x4):
    # (kept identical to provided code)
    rotation_matrix = matrix_4x4[:3, :3]
    translation_vector = matrix_4x4[:3, 3]

    rot = R.from_matrix(rotation_matrix)
    euler_angles = rot.as_euler('xyz', degrees=True)

    print(f"euler_angles {euler_angles}")

    ms.compute_matrix_from_translation_rotation_scale(
        rotationx=euler_angles[0] / 180 * np.pi,
        rotationy=euler_angles[1] / 180 * np.pi,
        rotationz=euler_angles[2] / 180 * np.pi,
        translationx=translation_vector[0],
        translationy=translation_vector[1],
        translationz=translation_vector[2],
        freeze=True
    )


def show_mesh(mesh_set, title="Intermediate Step", enabled=True):
    # (kept identical to provided code)
    if not enabled or mesh_set.mesh_number() == 0:
        if not enabled:
            print(f"[{title}] Visualization disabled. Skipping.")
        return
    print(f"[{title}] Visualizing result...")
    current_mesh = ms.current_mesh()
    o3d_mesh = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(current_mesh.vertex_matrix()),
        o3d.utility.Vector3iVector(current_mesh.face_matrix())
    )
    o3d_mesh.compute_vertex_normals()
    o3d_mesh.paint_uniform_color([0.7, 0.7, 0.7])
    o3d.visualization.draw_geometries([o3d_mesh], window_name=title)


def show_mesh_with_cutting_plane(ms, title, cut_z_value, enabled=True):
    """Visualize mesh, axes, and a cutting plane at given Z."""
    if not enabled or ms.mesh_number() == 0:
        if not enabled:
            print(f"[{title}] Visualization disabled. Skipping.")
        return

    print(f"[{title}] Visualizing mesh, axes, cutting plane (z={cut_z_value})...")

    # 1. Mesh
    current_mesh = ms.current_mesh()
    o3d_mesh = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(current_mesh.vertex_matrix()),
        o3d.utility.Vector3iVector(current_mesh.face_matrix())
    )
    o3d_mesh.compute_vertex_normals()
    o3d_mesh.paint_uniform_color([0.7, 0.7, 0.7])

    # 2. Axes
    mesh_bounds = o3d_mesh.get_axis_aligned_bounding_box()
    axis_size = max(mesh_bounds.get_extent()) * 0.5
    coord_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=axis_size, origin=[0, 0, 0])

    # 3. Cutting plane
    bounds_extent = mesh_bounds.get_extent()
    plane_width = bounds_extent[0] * 1.2
    plane_height = bounds_extent[1] * 1.2
    plane_depth = max(bounds_extent) * 0.005

    plane = o3d.geometry.TriangleMesh.create_box(width=plane_width, height=plane_height, depth=plane_depth)

    plane_center = mesh_bounds.get_center()
    plane.translate(
        (plane_center[0],
         plane_center[1],
         cut_z_value - plane_depth / 2),
        relative=False
    )
    plane.paint_uniform_color([1, 0, 0])

    # 4. Show together
    o3d.visualization.draw_geometries(
        [o3d_mesh, coord_frame, plane],
        window_name=title
    )


def flatten_bottom_hole_with_trimesh(ms: pymeshlab.MeshSet, target_z: float = 0.0) -> pymeshlab.MeshSet:
    """
    Move vertices of the largest boundary loop onto the given Z plane.
    """
    print("Flattening boundary loop with Trimesh...")
    current_mesh = ms.current_mesh()
    t_mesh = trimesh.Trimesh(vertices=current_mesh.vertex_matrix(), faces=current_mesh.face_matrix())

    loops_indices = find_boundary_loops(t_mesh)
    if not loops_indices:
        print("Warning: no boundary loop found; skipping flattening.")
        return ms

    largest_loop_indices = max(loops_indices, key=len)
    print(f"Found largest boundary loop ({len(largest_loop_indices)} vertices).")

    t_mesh.vertices[largest_loop_indices, 2] = target_z
    print(f"Projected all boundary loop vertices to Z={target_z}.")

    new_ms = pymeshlab.MeshSet()
    new_ms.add_mesh(pymeshlab.Mesh(vertex_matrix=t_mesh.vertices, face_matrix=t_mesh.faces))
    return new_ms


def fill_bottom_hole_constrained(ms: pymeshlab.MeshSet) -> pymeshlab.MeshSet:
    """
    Fill the largest boundary loop hole with a clean planar patch.
    """
    print("Filling bottom hole via constrained triangulation (Shapely + Trimesh)...")
    try:
        from shapely.geometry import Polygon
    except ImportError:
        print("\nError: 'shapely' required. Run 'pip install shapely'.")
        raise

    current_mesh = ms.current_mesh()
    t_mesh = trimesh.Trimesh(vertices=current_mesh.vertex_matrix(), faces=current_mesh.face_matrix())

    loops = find_boundary_loops(t_mesh)
    if not loops:
        print("Warning: no hole (boundary loop) to fill.")
        return ms
    largest_loop_indices = max(loops, key=len)
    print(f"Found largest boundary loop ({len(largest_loop_indices)} vertices).")

    loop_verts_3d = t_mesh.vertices[largest_loop_indices]
    loop_verts_2d = loop_verts_3d[:, :2]
    polygon_2d = Polygon(loop_verts_2d)

    new_vertices_2d, new_faces = trimesh.creation.triangulate_polygon(polygon_2d)

    z_coords = np.zeros((new_vertices_2d.shape[0], 1))
    new_vertices_3d = np.hstack((new_vertices_2d, z_coords))

    face_offset = len(t_mesh.vertices)
    new_faces_offset = new_faces + face_offset
    t_mesh.vertices = np.vstack([t_mesh.vertices, new_vertices_3d])
    t_mesh.faces = np.vstack([t_mesh.faces, new_faces_offset])

    t_mesh.merge_vertices()
    print(f"Filled hole with {len(new_faces)} new faces.")

    new_ms = pymeshlab.MeshSet()
    new_ms.add_mesh(pymeshlab.Mesh(vertex_matrix=t_mesh.vertices, face_matrix=t_mesh.faces))
    return new_ms


def run_refinement_pipeline(ms, cfg, forward_transform=None, inverse_transform=None):
    """
    Full post-processing pipeline (clean bottom + fill remaining holes).
    """
    print("\nStarting post-processing pipeline...")
    show_mesh_with_cutting_plane(ms, "Step 0: Appearance check Plane", 0, enabled=cfg.step_by_step_visualization)

    if forward_transform is not None:
        print("\n[Step 1] Aligning mesh with computed transform...")
        apply_transform_from_matrix(ms, forward_transform)
        show_mesh_with_cutting_plane(ms, "Step 1: After Alignment", 0, enabled=cfg.step_by_step_visualization)

    print("\n[Step 2] Running Screened Poisson reconstruction...")
    ms.generate_surface_reconstruction_screened_poisson(depth=8, fulldepth=8, preclean=True)
    show_mesh(ms, title="Step 2: After Poisson Reconstruction", enabled=cfg.step_by_step_visualization)

    if forward_transform is not None:
        cutting_plane_z = -1e-6
        print(f"\n[Step 3] Cutting bottom...")
        show_mesh_with_cutting_plane(ms, "Step 3: Preview Cutting Plane", cutting_plane_z,
                                     enabled=cfg.step_by_step_visualization)

        ms.compute_selection_by_condition_per_vertex(condselect=f'z < {cutting_plane_z}')
        if ms.current_mesh().selected_vertex_number() > 0:
            ms.meshing_remove_selected_vertices()
        show_mesh(ms, title="Step 3: After Cutting Bottom", enabled=cfg.step_by_step_visualization)

    print("\n[Step 4] Simplifying mesh ...")
    ms.meshing_decimation_quadric_edge_collapse(targetfacenum=20000, preservenormal=True)
    show_mesh(ms, title="Step 4: After Simplification", enabled=cfg.step_by_step_visualization)

    print("\n[Step 5] Remeshing ...")
    ms.meshing_isotropic_explicit_remeshing(targetlen=pymeshlab.PercentageValue(1))
    show_mesh(ms, title="Step 5: After Remeshing", enabled=cfg.step_by_step_visualization)

    print("\n[Step 6] 1st non-manifold repair ...")
    ms.meshing_repair_non_manifold_edges()
    ms.meshing_merge_close_vertices()
    show_mesh(ms, title="Step 6: After 1st Repair", enabled=cfg.step_by_step_visualization)

    if forward_transform is not None:
        print("\n[Step 7] Moving bottom boundary loop to z=0 (Trimesh)...")
        ms = flatten_bottom_hole_with_trimesh(ms, target_z=0.0)
        show_mesh(ms, title="Step 7: After Flattening Boundary Loop", enabled=cfg.step_by_step_visualization)

        print("\n[Step 8] Filling bottom hole via constrained triangulation...")
        ms = fill_bottom_hole_constrained(ms)
        show_mesh(ms, title="Step 8: After Constrained Fill", enabled=cfg.step_by_step_visualization)

        print("\n[Step 8.5] Mid non-manifold repair/cleanup...")
        ms.meshing_repair_non_manifold_edges()
        ms.meshing_merge_close_vertices()
        show_mesh(ms, title="Step 8.5: After Mid-Repair", enabled=cfg.step_by_step_visualization)

    print("\n[Step 9] Filling remaining holes...")
    ms.meshing_close_holes(maxholesize=5000)
    show_mesh(ms, title="Step 9: After Filling Other Holes", enabled=cfg.step_by_step_visualization)

    print("\n[Step 10] Final non-manifold repair/cleanup...")
    ms.meshing_repair_non_manifold_edges()
    ms.meshing_merge_close_vertices()
    show_mesh(ms, title="Step 10: After Final Repair", enabled=cfg.step_by_step_visualization)

    if inverse_transform is not None:
        print("\n[Step 11] Restoring final mesh to original frame...")
        apply_transform_from_matrix(ms, inverse_transform)
        show_mesh(ms, title="Step 11: After Reverting Transform", enabled=cfg.step_by_step_visualization)

    print(f"\nSaving final mesh to '{cfg.mesh_out_dir}'...")
    os.makedirs(os.path.dirname(cfg.mesh_out_dir), exist_ok=True)
    ms.save_current_mesh(cfg.mesh_out_dir)


if __name__ == "__main__":
    cfg = MeshRefinementConfig()
    ms = pymeshlab.MeshSet()
    try:
        ms.load_new_mesh(cfg.mesh_in_dir)
    except pymeshlab.PyMeshLabException:
        print(f"Warning: '{cfg.mesh_in_path}' not found; generating test mesh.")
        trimesh.creation.bowl().export(cfg.mesh_in_dir)
        ms.load_new_mesh(cfg.mesh_in_dir)

    if ms.mesh_number() > 0:
        if cfg.step_by_step_visualization:
            show_mesh(ms, title="Step 0: Original Mesh")

        # --- [Added] initial cleanup ---
        # Remove small disconnected pieces (floating noise) before processing.
        # Greatly improves pipeline stability.
        print("\n[Step 0.5] Removing small isolated pieces...")
        ms.meshing_remove_connected_component_by_diameter(
            mincomponentdiag=pymeshlab.PercentageValue(20.0)
        )
        show_mesh(ms, title="Step 0.5: After Initial Cleaning", enabled=cfg.step_by_step_visualization)

        # --- [End edit] ---

        forward_transform, inverse_transform = None, None
        if cfg.automatic_alignment:
            forward_transform, inverse_transform = calculate_transforms(ms)

        if forward_transform is not None:
            run_refinement_pipeline(ms, cfg, forward_transform=forward_transform, inverse_transform=inverse_transform)
        else:
            run_refinement_pipeline(ms, cfg)

        print("\nAll done.")
    else:
        print("\nFailed to load mesh; cannot start processing.")