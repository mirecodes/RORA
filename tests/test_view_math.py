import numpy as np

from functions.gui.viewcube import piece_at, slerp, view_for


def test_piece_at_face_edge_corner():
    assert piece_at([0.5, 0.0, 0.1]) == (1, 0, 0)
    assert piece_at([0.5, 0.45, 0.0]) == (1, 1, 0)
    assert piece_at([-0.5, -0.45, 0.48]) == (-1, -1, 1)
    assert piece_at([0.0, 0.0, 0.0]) is None


def test_view_for_up_vectors():
    d, up = view_for((0, 0, 1))
    assert np.allclose(d, [0, 0, 1]) and np.allclose(up, [-1, 0, 0])
    d, up = view_for((0, 0, -1))
    assert np.allclose(up, [1, 0, 0])
    d, up = view_for((1, 1, 0))
    assert np.allclose(d, np.array([1, 1, 0]) / np.sqrt(2)) and np.allclose(up, [0, 0, 1])


def test_slerp_endpoints_and_antipodes():
    a, b = np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    assert np.allclose(slerp(a, b, 0.0), a) and np.allclose(slerp(a, b, 1.0), b)
    assert np.isclose(np.linalg.norm(slerp(a, b, 0.3)), 1.0)
    mid = slerp(a, -a, 0.5)
    assert np.isclose(np.linalg.norm(mid), 1.0) and abs(np.dot(mid, a)) < 1e-6
    assert np.allclose(slerp(a, -a, 1.0), -a)


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
