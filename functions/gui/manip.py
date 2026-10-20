"""Rigid 4x4 deltas and the targets they move. Keyboard keys, panel fields, and the gizmo all build a
delta with these helpers and hand it to a Transformable, so a new input or a new target plugs in
without touching the others (e.g. a future SingleVectorTarget for per-arrow mouse control)."""
from typing import Callable, Protocol

import numpy as np
from scipy.spatial.transform import Rotation

from functions.math.geometry import normalize, rotmat

AXES = np.eye(3)

# key -> (kind, axis index, sign); shared by Align and Articulate
KEY_BINDINGS = {
    "w": ("move", 0, +1), "s": ("move", 0, -1),
    "d": ("move", 1, +1), "a": ("move", 1, -1),
    "space": ("move", 2, +1), "z": ("move", 2, -1),
    "n": ("turn", 0, +1), "b": ("turn", 0, -1),
    "j": ("turn", 1, +1), "h": ("turn", 1, -1),
    "i": ("turn", 2, +1), "u": ("turn", 2, -1),
}
KEY_HINTS = [("W/S", "move ±X"), ("D/A", "move ±Y"), ("Space/Z", "move ±Z"),
             ("N/B", "rotate ±X"), ("J/H", "rotate ±Y"), ("I/U", "rotate ±Z")]


def translation(v) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = np.asarray(v, dtype=float)
    return m


def rotation(axis, deg: float, pivot=(0.0, 0.0, 0.0)) -> np.ndarray:
    """Right-handed rotation by `deg` degrees about `axis` through `pivot`."""
    r = rotmat(axis, np.deg2rad(deg))
    p = np.asarray(pivot, dtype=float)
    m = np.eye(4)
    m[:3, :3] = r
    m[:3, 3] = p - r @ p
    return m


def key_delta(key: str, move_step: float, turn_deg: float, pivot) -> np.ndarray | None:
    """Delta for a bound key, or None for any other key."""
    if key not in KEY_BINDINGS:
        return None
    kind, axis, sign = KEY_BINDINGS[key]
    if kind == "move":
        return translation(AXES[axis] * sign * move_step)
    return rotation(AXES[axis], sign * turn_deg, pivot)


def to_fields(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(extrinsic xyz Euler angles in degrees, translation) for the panel fields."""
    euler = Rotation.from_matrix(matrix[:3, :3]).as_euler("xyz", degrees=True)
    return euler, matrix[:3, 3].copy()


def from_fields(euler_deg, trans) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = Rotation.from_euler("xyz", euler_deg, degrees=True).as_matrix()
    m[:3, 3] = trans
    return m


class Transformable(Protocol):
    def pivot(self) -> np.ndarray: ...

    def apply(self, delta: np.ndarray) -> None: ...


class AssemblyTarget:
    """Align: the accumulated world matrix of the mesh. Rotations pivot on the world origin so the
    ground plane (z = 0) and the axes stay put while the object turns."""

    def __init__(self, on_change: Callable[[np.ndarray], None] | None = None):
        self.matrix = np.eye(4)
        self.on_change = on_change

    def pivot(self) -> np.ndarray:
        return np.zeros(3)

    def apply(self, delta: np.ndarray) -> None:
        self.matrix = delta @ self.matrix
        if self.on_change:
            self.on_change(delta)

    def set_matrix(self, matrix: np.ndarray) -> None:
        """Jump to an absolute matrix (panel fields, Reset) by applying the difference as one delta."""
        self.apply(np.asarray(matrix, dtype=float) @ np.linalg.inv(self.matrix))


class VectorGroupTarget:
    """Articulate: every candidate vector of one part pair (dicts with 'center' and 'n', edited in place).
    Translation shifts every center; rotation turns every n, so each arrow rotates about its own center
    (the old key behaviour). The gizmo sits at the mean center."""

    def __init__(self, vectors: list[dict], on_change: Callable[[np.ndarray], None] | None = None):
        self.vectors = vectors
        self.on_change = on_change

    def pivot(self) -> np.ndarray:
        if not self.vectors:
            return np.zeros(3)
        return np.mean([np.asarray(v["center"], dtype=float) for v in self.vectors], axis=0)

    def apply(self, delta: np.ndarray) -> None:
        p = self.pivot()
        shift = delta[:3, :3] @ p + delta[:3, 3] - p  # zero for a rotation about the pivot
        for v in self.vectors:
            v["center"] = (np.asarray(v["center"], dtype=float) + shift).tolist()
            v["n"] = normalize(delta[:3, :3] @ normalize(v["n"])).tolist()
        if self.on_change:
            self.on_change(delta)
