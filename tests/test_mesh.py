import numpy as np
import trimesh

from functions.utils.mesh import close_link

COACD = {"threshold": 0.1, "resolution": 500, "mcts_iterations": 60, "seed": 0}


def _open_box():
    box = trimesh.creation.box()
    keep = box.face_normals[:, 2] < 0.5  # drop the top face (2 triangles)
    return box.vertices, box.faces[keep]


def test_close_link_closes_holes():
    out = close_link(*_open_box(), {"selfintersection": False}, COACD)
    assert out.is_watertight and abs(out.volume - 1.0) < 1e-6


def test_close_link_falls_back_to_coacd_union():
    out = close_link(*_open_box(), {"maxholesize": 1}, COACD)  # hole too large to close
    assert out.is_watertight and abs(out.volume - 1.0) < 0.05
