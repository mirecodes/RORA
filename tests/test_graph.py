import numpy as np
import trimesh

from functions.math.graph import adjacency, merge_cycles
from functions.pipeline.articulate import build_extrapoints_and_patches


def _grid(n=8):
    idx = lambda i, j: i * n + j
    faces = [f for i in range(n - 1) for j in range(n - 1)
             for f in ((idx(i, j), idx(i, j + 1), idx(i + 1, j)), (idx(i, j + 1), idx(i + 1, j + 1), idx(i + 1, j)))]
    return idx, adjacency(np.array(faces), n * n)


def test_merge_cycles_keeps_ordered_raw_cycles():
    idx, adj = _grid()
    a = np.array([idx(1, 1), idx(1, 2), idx(2, 2), idx(2, 1)])
    b = np.array([idx(1, 4), idx(1, 5), idx(2, 5), idx(2, 4)])  # 2 hops from a
    far = np.array([idx(6, 1), idx(6, 2), idx(7, 2)])
    merged = merge_cycles(adj, [a, b, far], max_hops=2, min_size=0)
    assert len(merged) == 2
    cycle, raw = merged[0]
    assert set(cycle) == set(a) | set(b)
    assert all(np.array_equal(x, y) for x, y in zip(raw, [a, b]))


def test_patch_uses_cycle_order_not_vertex_ids():
    # Circle whose vertex ids are shuffled: sorted ids != boundary order
    t = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    perm = np.random.default_rng(0).permutation(len(t))
    verts = np.zeros((len(t), 3))
    verts[perm] = np.column_stack([np.cos(t), np.sin(t), np.zeros_like(t)])
    unicon = {"src": 1, "cycle": np.sort(perm), "raw_cycles": [perm]}
    P, F = build_extrapoints_and_patches([unicon], verts)
    area = trimesh.Trimesh(P[1][0], F[1][0], process=False).area
    assert abs(area - np.pi) < 0.05 * np.pi
