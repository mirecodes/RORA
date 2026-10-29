import numpy as np
import trimesh

from functions.math.graph import label_vertices


def _folded_strip(n=11, gap=0.05):
    # bottom strip z=0 and top strip z=gap, x in [0, 1], joined only at x=1; plus one isolated triangle
    xs = np.linspace(0.0, 1.0, n)
    verts = [(x, y, z) for z in (0.0, gap) for x in xs for y in (0.0, 1.0)]
    vid = lambda s, i, j: s * 2 * n + 2 * i + j
    faces = []
    for s in (0, 1):
        for i in range(n - 1):
            faces += [(vid(s, i, 0), vid(s, i + 1, 0), vid(s, i + 1, 1)), (vid(s, i, 0), vid(s, i + 1, 1), vid(s, i, 1))]
    faces += [(vid(0, n - 1, 0), vid(1, n - 1, 0), vid(1, n - 1, 1)), (vid(0, n - 1, 0), vid(1, n - 1, 1), vid(0, n - 1, 1))]
    verts += [(0.1, 0.5, 0.2), (0.2, 0.5, 0.2), (0.1, 0.6, 0.2)]  # isolated, nearest to the top strip's x~0.1
    faces += [(len(verts) - 3, len(verts) - 2, len(verts) - 1)]
    return np.array(verts), np.array(faces)


def test_labels_follow_mesh_edges_not_euclidean_gaps():
    verts, faces = _folded_strip()
    part1 = trimesh.creation.box(extents=(0.6, 1.2, 0.02), transform=trimesh.transformations.translation_matrix((0.25, 0.5, 0.0)))
    part2 = trimesh.creation.box(extents=(0.12, 1.2, 0.02), transform=trimesh.transformations.translation_matrix((0.95, 0.5, 0.05)))
    labels = label_vertices(verts, faces, [[], [part1], [part2]], use_signed_dist=False)
    top_near_x0 = (verts[:, 2] == 0.05) & (verts[:, 0] < 0.2)
    assert (labels[top_near_x0] == 2).all()  # Euclidean nearest is part 1 right below; geodesic reaches part 2
    assert (labels[-3:] == 2).all()          # unreachable on the mesh -> kNN vote picks the top strip
    assert (labels >= 0).all()
