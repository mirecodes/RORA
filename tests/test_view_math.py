import numpy as np

from functions.gui.gizmo import axis_drag_distance, ring_drag_angle
from functions.gui.viewcube import piece_at, ray_box, slerp, view_for


def test_piece_at_face_edge_corner():
    assert piece_at([0.5, 0.0, 0.1]) == (1, 0, 0)
    assert piece_at([0.5, 0.45, 0.0]) == (1, 1, 0)
    assert piece_at([-0.5, -0.45, 0.48]) == (-1, -1, 1)
    assert piece_at([0.0, 0.0, 0.0]) is None


def test_ray_box_hits_nearest_face():
    assert np.allclose(ray_box([3.0, 0.1, 0.2], [-1.0, 0, 0]), [0.5, 0.1, 0.2])
    assert np.allclose(ray_box([0.2, 0.0, 3.0], [0, 0, -1.0]), [0.2, 0.0, 0.5])
    assert ray_box([3.0, 2.0, 0.0], [-1.0, 0, 0]) is None   # passes beside the cube
    assert ray_box([3.0, 0.0, 0.0], [1.0, 0, 0]) is None    # points away


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


def test_axis_drag_distance():
    # axis drawn 100 px to the right for a world segment of length 2
    assert np.isclose(axis_drag_distance([50, 0], [0, 0], [100, 0], 2.0), 1.0)
    assert np.isclose(axis_drag_distance([0, 40], [0, 0], [100, 0], 2.0), 0.0)
    assert np.isclose(axis_drag_distance([-25, 10], [0, 0], [100, 0], 2.0), -0.5)
    assert axis_drag_distance([10, 10], [5, 5], [5, 5], 1.0) == 0.0  # axis points at the camera


def test_ring_drag_angle():
    c = np.array([0.0, 0.0])
    assert np.isclose(ring_drag_angle([10, 0], [0, 10], c), 90.0)
    assert np.isclose(ring_drag_angle([0, 10], [10, 0], c), -90.0)
    assert ring_drag_angle([1, 0], [0, 10], c) == 0.0  # too close to the center


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
