import numpy as np

from functions.math.connection import fuse_connections


def _unicons(scale):
    # part 1 -> 2 and 2 -> 1, two cycles each; the matching must not depend on the object's size
    def u(src, dst, c, n):
        return {"src": src, "dst": dst, "center": scale * np.asarray(c, float), "pca_normal": np.asarray(n, float)}
    return [u(1, 2, [0, 0, 0], [0, 0, 1]), u(1, 2, [1, 0, 0], [1, 0, 0]),
            u(2, 1, [0.05, 0, 0], [1, 0, 0]), u(2, 1, [0.95, 0, 0], [0, 0, 1])]


def test_fusion_cost_is_scale_free():
    runs = []
    for s in (0.01, 1.0, 100.0):
        bicons = fuse_connections(_unicons(s), scale=2.0 * s)
        runs.append([(tuple(b["a"]["center"] / s), tuple(b["b"]["center"] / s), round(b["cost"], 9)) for b in bicons])
    assert runs[0] == runs[1] == runs[2]
