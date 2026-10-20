"""Debug viewers (close the window to continue)."""
import numpy as np
import pymeshlab
import vedo

from functions.math.geometry import normalize
from functions.math.connection import merge_lines, plane_intersections, unicon_normal
from functions.visualize.style import BG_RGB, PASTEL, arrow_params, label_colors, pastel, pastel_hex


def _show(actors, title: str, **kwargs):
    vedo.Plotter(bg="white", title=title, size=(1800, 1800)).show(actors, **kwargs).close()


def _arrow(c, n, color, size, big: bool = False) -> vedo.Arrow:
    arrow_len, shaft_rad, head_rad, head_len = size[:4]
    s = (1.4, 1.3, 1.2) if big else (1.0, 1.0, 1.0)
    return vedo.Arrow(c, c + arrow_len * n, c=color, shaft_radius=shaft_rad * s[0],
                      head_radius=head_rad * s[1], head_length=head_len * s[2])


def show_meshset(ms: pymeshlab.MeshSet, title: str):
    """Current mesh of a MeshSet, with vertex colors if present."""
    if not isinstance(ms, pymeshlab.MeshSet) or ms.mesh_number() == 0:
        print(f"[Debug Viewer] Skipping: Invalid MeshSet for '{title}'")
        return
    print(f"[Debug Viewer] Showing: {title}")
    try:
        m = ms.current_mesh()
        verts, faces = m.vertex_matrix(), m.face_matrix()
        if verts.size == 0 or faces.size == 0:
            print(f"[Debug Viewer] Skipping '{title}': No geometry to show.")
            return
        actor = vedo.Mesh([verts, faces]).c("lightblue")
        if m.has_vertex_color():
            colors = m.vertex_color_matrix()
            actor.pointcolors = (colors[:, :3] * 255).astype("uint8") if colors.max() <= 1.0 else colors[:, :3]
        vedo.Plotter(title=title, axes=1, size=(1800, 1200)).show(actor, title).close()
    except Exception as e:
        print(f"[Debug Viewer] Error displaying '{title}': {e}")


def show_labels(verts, faces, vert_label, title: str = "Segmented Parts Preview"):
    """Mesh colored by part label (transparent to show the inside)."""
    mesh = vedo.Mesh([verts, faces])
    mesh.pointcolors = label_colors(vert_label)
    _show([mesh.alpha(0.4)], title, viewup="z")


def show_cycles(verts, faces, cycles, cycle_neighbors, idx_part: int, vert_label=None,
                title: str = "All Boundary Cycles", show_none_cycles: bool = False):
    """Boundary cycles of a part, each colored by the neighbor part it touches."""
    part_color = pastel_hex(idx_part)
    if vert_label is None:
        actors = [vedo.Mesh([verts, faces]).c(part_color).alpha(0.35)]
    else:
        is_part = vert_label[faces[:, 0]] == idx_part
        actors = [vedo.Mesh([verts, f]).c(c).alpha(a) for f, c, a in
                  ((faces[~is_part], "lightgray", 0.15), (faces[is_part], part_color, 0.35)) if len(f)]

    diag = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
    sphere_r = (diag * 0.005 if np.isfinite(diag) and diag > 0 else 0.005) * 1.2
    for i, (cycle, nbrs) in enumerate(zip(cycles, cycle_neighbors)):
        if not nbrs and not show_none_cycles:
            continue
        target = nbrs[0] if nbrs and isinstance(nbrs[0], int) else idx_part
        actors.append(vedo.Spheres(verts[np.asarray(cycle, dtype=int)], r=sphere_r, c=pastel_hex(target), res=8))
        r, g, b = pastel(target)
        print(f"[info] Cycle {i + 1} (\033[38;2;{r};{g};{b}m■\033[0m): "
              f"Part {idx_part} -> {','.join(map(str, nbrs)) if nbrs else 'N'}")
    _show(actors, title, viewup="z")


def show_axis_estimation(verts, faces, idx_pos, idx_neg, planes, center, title: str = "k-hop neighbors and plane",
                         cycle_indices=None, idx_part: int = 1, cycle_color: str | None = None):
    """k-hop samples (positives in part color), the cycle, the fitted plane(s) and their normal/intersection."""
    actors = [vedo.Mesh([verts, faces]).c("lightgray").alpha(0.18)]

    khop = np.union1d(idx_pos, idx_neg).astype(int)
    khop_faces = faces[np.isin(faces, khop).any(axis=1)]
    if len(khop_faces):
        rgb = np.tile(np.array([230, 230, 230], dtype=np.uint8), (len(verts), 1))
        rgb[idx_neg] = PASTEL[-1]
        rgb[idx_pos] = pastel(idx_part)
        khop_mesh = vedo.Mesh([verts, khop_faces])
        khop_mesh.pointcolors = rgb
        actors.append(khop_mesh.alpha(0.7).lw(0.8).lc("black"))

    if cycle_indices is not None and len(cycle_indices):
        actors.append(vedo.Spheres(verts[cycle_indices], r=0.006, c=cycle_color or pastel_hex(idx_part), res=8))

    plane_colors = ["#9EAEC4", "#C4AE9E", "#9EC4AF", "#C49EC1"]
    for i, (n, d) in enumerate(planes):
        color = plane_colors[i % len(plane_colors)] if len(planes) > 1 else "#B3B3B3"
        actors.append(vedo.Plane(pos=center - (np.dot(center, n) + d) * n, normal=n, s=(1.0, 1.0)).c(color).alpha(0.25))

    # One plane -> its normal (orange); several -> intersection of the first two (blue)
    size = arrow_params(verts)
    print(f"[info] {title}")
    if len(planes) == 1:
        actors.append(_arrow(center, normalize(planes[0][0]), "orange", size))
        print("  \033[38;2;255;127;14m[Normal Vector - Orange]\033[0m Single Plane Normal")
    elif len(planes) > 1:
        n_inter = np.cross(normalize(planes[0][0]), normalize(planes[1][0]))
        if np.linalg.norm(n_inter) > 1e-6:
            actors.append(_arrow(center, normalize(n_inter), "dodgerblue", size))
            print("  \033[38;2;30;144;255m[Intersection Vector - Blue]\033[0m Multi-plane Intersection Vector")
    _show(actors, title, viewup="z")


def show_bicons(verts, faces, bicons):
    """Per bicon: (1) single-plane normals, (2) multi-plane intersection lines, (3) the resulting 3-axis frame."""
    size = arrow_params(verts)
    for idx_b, bicon in enumerate(bicons):
        a, b = bicon.get("a"), bicon.get("b")
        if not bicon.get("parts") or not a or not b:
            continue
        i, j = bicon["parts"]
        tag = f"Bicon #{idx_b} (parts {i} ↔ {j})"
        print(f"[info] Visualizing {tag}. Close window to proceed.")

        rgb = np.tile(BG_RGB, (len(verts), 1))
        for color, ids in ((pastel(j), [b.get("idx_pos", []), a.get("idx_neg", [])]),
                           (pastel(i), [a.get("idx_pos", []), b.get("idx_neg", [])])):
            ids = np.concatenate([np.asarray(x, dtype=int) for x in ids])
            rgb[ids] = color
        mesh = vedo.Mesh([verts, faces])
        mesh.pointcolors = rgb
        mesh.alpha(0.4).pickable(False)

        ca, cb, c = (np.asarray(x, dtype=float) for x in (a["center"], b["center"], bicon["center"]))
        conn = vedo.Line(ca, cb).c("orange").lw(3)
        n_pair = normalize(bicon["normal"])

        # 1) Single-plane normals
        nA, nB = unicon_normal(a), unicon_normal(b)
        nB = -nB if np.dot(nA, nB) < 0.0 else nB
        print(f"[info] {tag} - Window 1: Single-plane Normal Match")
        print(f"  \033[38;2;255;127;14m[Normal Vector - Orange]\033[0m Single-plane Normal vectors for Part {i}, Part {j}, and Merged Bicon Normal")
        vedo.Plotter(title=f"Bicon #{idx_b} (Single-plane Normal Match): parts {i} ↔ {j}", axes=0, size=(1800, 1800)).show(
            [mesh, conn, _arrow(ca, nA, "orange", size), _arrow(cb, nB, "orange", size),
             _arrow(c, n_pair, "orange", size, big=True), vedo.Sphere(pos=c, r=size[4] * 1.2).c("orange")],
            interactive=True).close()

        # 2) Multi-plane intersection lines
        lines_a = plane_intersections((a.get("multi_plane") or {}).get("plane") or [])
        lines_b = plane_intersections((b.get("multi_plane") or {}).get("plane") or [])
        if not lines_a and not lines_b:
            continue
        merged = merge_lines(lines_a, lines_b)
        print(f"[info] {tag} - Window 2: Multi-plane Intersection Match")
        print("  \033[38;2;30;144;255m[Intersection Vector - Blue]\033[0m Multi-plane Intersection Lines A, B & Merged Lines")
        vedo.Plotter(title=f"Bicon #{idx_b} (Multi-plane Intersection Match): parts {i} ↔ {j}", axes=0, size=(1800, 1800)).show(
            [mesh, conn] + [_arrow(ca, l, "dodgerblue", size) for l in lines_a]
            + [_arrow(cb, l, "dodgerblue", size) for l in lines_b]
            + [_arrow(c, l, "dodgerblue", size, big=True) for l in merged],
            interactive=True).close()

        # 3) Frame: normal, first merged line, their cross product
        n_third = np.cross(n_pair, merged[0])
        if np.linalg.norm(n_third) <= 1e-6:
            continue
        print(f"[info] {tag} - Window 3: 3rd Perpendicular Coordinate Frame")
        print("  1. \033[38;2;255;127;14m[Normal Vector - Orange]\033[0m Main Plane Normal")
        print("  2. \033[38;2;30;144;255m[Intersection Vector - Blue]\033[0m Intersection Line")
        print("  3. \033[38;2;46;139;87m[Cross Product Vector - Green]\033[0m Perpendicular Axis (Cross Product)")
        vedo.Plotter(title=f"Bicon #{idx_b} (3rd Perpendicular Coordinate Frame): parts {i} ↔ {j}", axes=0, size=(1800, 1800)).show(
            [mesh, _arrow(c, n_pair, "orange", size, big=True), _arrow(c, merged[0], "dodgerblue", size, big=True),
             _arrow(c, normalize(n_third), "mediumseagreen", size, big=True)],
            interactive=True).close()
