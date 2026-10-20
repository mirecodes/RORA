import numpy as np
import vedo

from functions.gui.manip import (AssemblyTarget, VectorGroupTarget, from_fields, key_delta, rotation,
                                 to_fields, translation)
from functions.math.geometry import normalize, rotmat


def old_key(asm, k, angle, step):
    """Copy of the deleted transform.key_press_callback (reference behaviour)."""
    {"u": lambda: asm.rotate_z(-angle), "i": lambda: asm.rotate_z(angle),
     "h": lambda: asm.rotate_y(-angle), "j": lambda: asm.rotate_y(angle),
     "b": lambda: asm.rotate_x(-angle), "n": lambda: asm.rotate_x(angle),
     "w": lambda: asm.shift(step, 0, 0), "s": lambda: asm.shift(-step, 0, 0),
     "d": lambda: asm.shift(0, step, 0), "a": lambda: asm.shift(0, -step, 0),
     "space": lambda: asm.shift(0, 0, step), "z": lambda: asm.shift(0, 0, -step)}[k]()


def test_rotation_keeps_pivot_fixed():
    m = rotation([0, 0, 1], 37.0, pivot=[1.0, 2.0, 3.0])
    assert np.allclose(m @ [1.0, 2.0, 3.0, 1.0], [1.0, 2.0, 3.0, 1.0])
    assert np.allclose(translation([1, 2, 3])[:3, 3], [1, 2, 3])


def test_align_keys_match_old_vedo_assembly():
    asm = vedo.Assembly((vedo.Mesh([[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]]]),))
    target = AssemblyTarget()
    for key in ["u", "w", "i", "i", "space", "b", "d", "n", "h", "j", "s", "z", "a"]:
        target.apply(key_delta(key, 0.5, 1.0, target.pivot()))
        old_key(asm, key, 1.0, 0.5)
    assert np.allclose(target.matrix, asm.transform.matrix, atol=1e-9)
    assert key_delta("q", 0.5, 1.0, target.pivot()) is None


def test_set_matrix_and_fields_round_trip():
    seen = []
    target = AssemblyTarget(on_change=seen.append)
    goal = from_fields([10.0, -20.0, 30.0], [0.1, 0.2, 0.3])
    target.set_matrix(goal)
    assert np.allclose(target.matrix, goal) and len(seen) == 1
    euler, trans = to_fields(target.matrix)
    assert np.allclose(euler, [10.0, -20.0, 30.0]) and np.allclose(trans, [0.1, 0.2, 0.3])


def test_vector_group_matches_old_key_handler():
    vectors = [{"center": [0.0, 0.0, 0.0], "n": [1.0, 0.0, 0.0]},
               {"center": [1.0, 1.0, 0.0], "n": [0.0, 1.0, 0.0]}]
    expected = [dict(v) for v in vectors]
    target = VectorGroupTarget(vectors)
    th = np.deg2rad(1.5)
    for key in ["w", "i", "i", "space", "n"]:
        target.apply(key_delta(key, 0.1, 1.5, target.pivot()))
        d = {"w": (0.1, 0, 0), "space": (0, 0, 0.1)}.get(key, (0, 0, 0))
        R = {"i": rotmat([0, 0, 1], th), "n": rotmat([1, 0, 0], th)}.get(key)
        for v in expected:  # old select_joint_vectors.on_key
            v["center"] = (np.asarray(v["center"]) + d).tolist()
            if R is not None:
                v["n"] = normalize(R @ normalize(v["n"])).tolist()
    for got, want in zip(vectors, expected):
        assert np.allclose(got["center"], want["center"]) and np.allclose(got["n"], want["n"])


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
