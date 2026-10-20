import open3d as o3d
import trimesh

from functions import find_boundary_loops


# These functions use find_boundary_loops (imported, not redefined).

def show_mesh(ms, title="Intermediate Step", enabled=True, verbose=False, highlight_boundary_loops=False):
    '''
    General mesh display function.
    Highlights the largest boundary loop in red and other loops in blue.
    '''
    if not enabled or ms.mesh_number() == 0:
        if not enabled and verbose:
            print(f"[info] Visualization disabled. ({title})")
        return

    if verbose:
        print(f"[info] Visualize the mesh. ({title})")

    current_mesh = ms.current_mesh()
    vertices = current_mesh.vertex_matrix()
    faces = current_mesh.face_matrix()

    # 1. Base mesh
    o3d_mesh = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(vertices),
                                         o3d.utility.Vector3iVector(faces))
    o3d_mesh.compute_vertex_normals()
    o3d_mesh.paint_uniform_color([0.7, 0.7, 0.7])

    geometries_to_draw = [o3d_mesh]

    # 2. [Upgrade] Color-coded LineSets for all boundary loops
    if highlight_boundary_loops:
        t_mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
        loops = find_boundary_loops(t_mesh, verbose=True)

        if loops:
            # Sort by length to find the largest
            loops.sort(key=len, reverse=True)
            largest_loop_indices = loops[0]
            other_loop_indices_list = loops[1:]

            points = vertices  # LineSet uses all mesh vertices

            # LineSet 1: largest loop (red)
            largest_lines = []
            for i in range(len(largest_loop_indices) - 1):
                largest_lines.append([largest_loop_indices[i], largest_loop_indices[i + 1]])
            largest_lines.append([largest_loop_indices[-1], largest_loop_indices[0]])

            largest_line_set = o3d.geometry.LineSet()
            largest_line_set.points = o3d.utility.Vector3dVector(points)
            largest_line_set.lines = o3d.utility.Vector2iVector(largest_lines)
            largest_line_set.paint_uniform_color([1, 0, 0])  # red
            geometries_to_draw.append(largest_line_set)

            # LineSet 2: other loops (blue)
            if other_loop_indices_list:
                other_lines = []
                for loop in other_loop_indices_list:
                    for i in range(len(loop) - 1):
                        other_lines.append([loop[i], loop[i + 1]])
                    other_lines.append([loop[-1], loop[0]])

                other_line_set = o3d.geometry.LineSet()
                other_line_set.points = o3d.utility.Vector3dVector(points)
                other_line_set.lines = o3d.utility.Vector2iVector(other_lines)
                other_line_set.paint_uniform_color([0, 0, 1])  # blue
                geometries_to_draw.append(other_line_set)

    # 3. Visualize
    o3d.visualization.draw_geometries(geometries_to_draw, window_name=title)


def show_mesh_with_cutting_plane(ms, title, cut_z_value, enabled=True, verbose=False, highlight_boundary_loops=False):
    '''
    Visualize the mesh with cutting plane and coordinate axis.
    Highlights the largest boundary loop in yellow and other loops in blue.
    '''
    if not enabled or ms.mesh_number() == 0:
        if not enabled and verbose:
            print(f"[info] Visualization disabled. ({title})")
        return

    if verbose:
        print(f"[info] Visualize mesh, coordinate axis, cutting plane(z={cut_z_value}). ({title})")

    # 1. Mesh, axes, cutting plane
    current_mesh = ms.current_mesh()
    vertices = current_mesh.vertex_matrix()
    faces = current_mesh.face_matrix()
    o3d_mesh = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(vertices),
                                         o3d.utility.Vector3iVector(faces))
    o3d_mesh.compute_vertex_normals()
    o3d_mesh.paint_uniform_color([0.7, 0.7, 0.7])

    mesh_bounds = o3d_mesh.get_axis_aligned_bounding_box()
    mesh_center = mesh_bounds.get_center()
    axis_size = max(mesh_bounds.get_extent()) * 0.5
    coord_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=axis_size, origin=mesh_center)

    plane = o3d.geometry.TriangleMesh.create_box(
        width=mesh_bounds.get_extent()[0] * 1.2,
        height=mesh_bounds.get_extent()[1] * 1.2,
        depth=max(mesh_bounds.get_extent()) * 0.005
    )
    plane.translate((mesh_center[0], mesh_center[1], cut_z_value - plane.get_max_bound()[2]), relative=False)
    plane.paint_uniform_color([1, 0, 0])  # cutting plane in red

    geometries_to_draw = [o3d_mesh, coord_frame, plane]

    # 2. [Upgrade] Color-coded LineSets for all boundary loops
    if highlight_boundary_loops:
        t_mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
        loops = find_boundary_loops(t_mesh, verbose=True)

        if loops:
            loops.sort(key=len, reverse=True)
            largest_loop_indices = loops[0]
            other_loop_indices_list = loops[1:]

            points = vertices

            # LineSet 1: largest loop (yellow)
            largest_lines = []
            for i in range(len(largest_loop_indices) - 1):
                largest_lines.append([largest_loop_indices[i], largest_loop_indices[i + 1]])
            largest_lines.append([largest_loop_indices[-1], largest_loop_indices[0]])

            largest_line_set = o3d.geometry.LineSet()
            largest_line_set.points = o3d.utility.Vector3dVector(points)
            largest_line_set.lines = o3d.utility.Vector2iVector(largest_lines)
            largest_line_set.paint_uniform_color([1, 1, 0])  # yellow (distinct from red plane)
            geometries_to_draw.append(largest_line_set)

            # LineSet 2: other loops (blue)
            if other_loop_indices_list:
                other_lines = []
                for loop in other_loop_indices_list:
                    for i in range(len(loop) - 1):
                        other_lines.append([loop[i], loop[i + 1]])
                    other_lines.append([loop[-1], loop[0]])

                other_line_set = o3d.geometry.LineSet()
                other_line_set.points = o3d.utility.Vector3dVector(points)
                other_line_set.lines = o3d.utility.Vector2iVector(other_lines)
                other_line_set.paint_uniform_color([0, 0, 1])  # blue
                geometries_to_draw.append(other_line_set)

    # 3. Visualize
    o3d.visualization.draw_geometries(geometries_to_draw, window_name=title)