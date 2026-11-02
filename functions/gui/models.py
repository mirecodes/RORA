"""Pure interaction state for the Segment and Articulate scenes (no Qt/VTK)."""
import copy
from collections import defaultdict

import numpy as np


class PartAssignment:
    """Fragment -> part ownership. Fragments are 1-based; owner[0] is an unused slot.
    Mode 0 is view-only. In mode k, assign() moves a fragment to part k and undo() reverts that
    fragment's last assignment."""

    def __init__(self, n_fragments: int, parts_num: int):
        self.parts_num = parts_num
        self.owner = [0] + [1] * n_fragments
        self.prev = list(self.owner)
        self.mode = 0

    def set_mode(self, mode: int) -> None:
        self.mode = max(0, min(int(mode), self.parts_num))

    def cycle_mode(self) -> int:
        self.mode = (self.mode + 1) % (self.parts_num + 1)
        return self.mode

    def assign(self, i: int) -> bool:
        if self.mode == 0:
            return False
        self.prev[i], self.owner[i] = self.owner[i], self.mode
        return True

    def undo(self, i: int) -> bool:
        if self.mode == 0:
            return False
        self.owner[i] = self.prev[i]
        return True

    def counts(self) -> dict[int, int]:
        return {p: self.owner[1:].count(p) for p in range(1, self.parts_num + 1)}


def group_fragments(fragments, owner, parts_num: int) -> list[list]:
    """parts[0..parts_num] (lists of fragments) from an owner list."""
    parts = [[] for _ in range(parts_num + 1)]
    for i, fragment in enumerate(fragments, start=1):
        parts[owner[i]].append(fragment)
    return parts


NEXT_STATE = {"None": "Revolute", "Revolute": "Prismatic"}  # anything else -> "None"


def group_pairs(bicons) -> list[tuple[tuple[int, int], list[dict]]]:
    """Bicons grouped by unordered part pair (p <= q) in first-seen order; the (0, 0) pair is skipped."""
    pairs = defaultdict(list)
    for bicon in bicons:
        p, q = int(bicon["a"]["src"]), int(bicon["a"]["dst"])
        pairs[(min(p, q), max(p, q))].append(bicon)
    return [(k, v) for k, v in pairs.items() if k != (0, 0)]


def valid_vectors(group) -> list[tuple[dict, dict]]:
    """(bicon, vector) for every vector with a finite, non-zero `n`; a missing `center` is filled from
    the bicon so the vector can be moved."""
    out = []
    for bicon in group:
        for v in bicon.get("vectors") or []:
            if v.get("n") is None:
                continue
            n = np.asarray(v["n"], dtype=float)
            if not np.isfinite(n).all() or np.linalg.norm(n) < 1e-12:
                continue
            v.setdefault("center", [float(c) for c in bicon.get("center", [0.0, 0.0, 0.0])])
            out.append((bicon, v))
    return out


def cycle_state(vector: dict, counter: list[int]) -> str:
    """None -> Revolute -> Prismatic -> None. Each Revolute pick gets the next per-pair `order`."""
    state = NEXT_STATE.get(vector.get("state", "None"), "None")
    vector["state"] = state
    if state == "Revolute":
        counter[0] += 1
        vector["order"] = counter[0]
    elif state == "None":
        vector["order"] = None
    return state


JOINT_STATES = ("Revolute", "Prismatic")


def picked(vectors) -> list[dict]:
    """The vectors selected as a joint (Revolute or Prismatic)."""
    return [v for v in vectors or [] if v.get("state") in JOINT_STATES]


class ManualJoints:
    """User study condition A: joints authored one at a time from an X/Y/Z triad at the world origin.
    Triad arrows cycle state like suggested vectors; confirm() stores the whole triad with the chosen
    parent/child, and edit(i) brings a confirmed one back as the active triad (cancel() keeps the original).
    bicons() hands the picked arrows of every confirmed joint to joints_from_bicons."""

    def __init__(self, parts_num: int):
        self.parts_num = parts_num
        self.parent, self.child = 1, min(2, parts_num)
        self.triad: list[dict] | None = None
        self.editing: int | None = None   # index in `confirmed` the active triad replaces on confirm
        self.counter = [0]
        self.confirmed: list[dict] = []   # {"parent", "child", "triad"}

    def can_add(self) -> bool:
        return self.triad is None and self.parent != self.child

    def new_joint(self) -> bool:
        if not self.can_add():
            return False
        self.triad = [{"center": [0.0, 0.0, 0.0], "n": [float(x) for x in e], "state": "None", "axis": a}
                      for a, e in zip("XYZ", np.eye(3))]
        self.counter = [0]
        return True

    def edit(self, i: int) -> bool:
        if self.triad is not None:
            return False
        joint = self.confirmed[i]
        self.triad = copy.deepcopy(joint["triad"])
        self.parent, self.child, self.editing = joint["parent"], joint["child"], i
        self.counter = [max(v.get("order") or 0 for v in self.triad)]
        return True

    def cancel(self) -> None:
        """Drop the active triad: a new joint is discarded, an edited one keeps its confirmed version."""
        self.triad = self.editing = None

    def can_confirm(self) -> bool:
        return bool(picked(self.triad)) and self.parent != self.child

    def confirm(self) -> bool:
        if not self.can_confirm():
            return False
        joint = {"parent": self.parent, "child": self.child, "triad": self.triad}
        if self.editing is None:
            self.confirmed.append(joint)
        else:
            self.confirmed[self.editing] = joint
        self.triad = self.editing = None
        return True

    def remove(self, i: int) -> bool:
        if self.triad is not None:
            return False
        del self.confirmed[i]
        return True

    def bicons(self) -> list[dict]:
        return [{"a": {"src": j["parent"], "dst": j["child"]}, "vectors": picked(j["triad"])} for j in self.confirmed]

    @staticmethod
    def describe(joint: dict) -> str:
        arrows = ", ".join(f"{v['state']} {v['axis']}" for v in picked(joint["triad"]))
        return f"{joint['parent']} → {joint['child']} · {arrows}"
