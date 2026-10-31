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


def test_fusion_merges_near_antiparallel_normals():
    # the i->j and j->i cycles of one joint face each other (~178 deg apart): one bicon, not two
    tilt = np.deg2rad(2.0)
    unicons = [{"src": 1, "dst": 2, "center": np.zeros(3), "pca_normal": np.array([0.0, 0.0, 1.0])},
               {"src": 2, "dst": 1, "center": np.array([0.0, 0.0, 0.01]),
                "pca_normal": np.array([np.sin(tilt), 0.0, -np.cos(tilt)])}]
    bicons = fuse_connections(unicons, scale=1.0)
    assert len(bicons) == 1
    assert bicons[0]["cost"] < 0.02
    assert bicons[0]["normal"] @ np.array([0.0, 0.0, 1.0]) > 0.999
