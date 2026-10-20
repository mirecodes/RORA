"""Reciprocal loop pairs (RLPs): match part i->j loops with part j->i loops."""
from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment

from functions.math.geometry import normalize


def loop_normal(res: dict) -> np.ndarray:
    """Loop normal: linear separator plane if trained, else the loop's PCA normal."""
    plane = (res.get("linear") or {}).get("plane")
    return normalize(plane[0][0] if plane else res.get("pca_normal", (0.0, 0.0, 1.0)))


def plane_intersections(planes) -> list[np.ndarray]:
    """Unit directions of the intersection lines of every plane pair [(n, d), ...]."""
    lines = []
    for a in range(len(planes)):
        for b in range(a + 1, len(planes)):
            n = np.cross(planes[a][0], planes[b][0])
            if np.linalg.norm(n) > 1e-6:
                lines.append(normalize(n))
    return lines


def merge_lines(lines_a, lines_b, cos_min: float = 0.866025) -> list[np.ndarray]:
    """Average greedy-matched direction pairs (within ~30 deg, sign-agnostic), then append the unmatched."""
    pairs = sorted(((abs(np.dot(la, lb)), i, j) for i, la in enumerate(lines_a) for j, lb in enumerate(lines_b)),
                   key=lambda x: x[0], reverse=True)
    merged, used_a, used_b = [], set(), set()
    for dot, i, j in pairs:
        if dot < cos_min:
            break
        if i in used_a or j in used_b:
            continue
        lb = lines_b[j] if np.dot(lines_a[i], lines_b[j]) >= 0.0 else -lines_b[j]
        merged.append(normalize(lines_a[i] + lb))
        used_a.add(i); used_b.add(j)
    merged += [la for i, la in enumerate(lines_a) if i not in used_a]
    merged += [lb for j, lb in enumerate(lines_b) if j not in used_b]
    return merged


def cluster_rlps(results: list[dict], *, w_pos: float = 1.0, w_ang: float = 0.5,
                 cost_max: float | None = None) -> list[dict]:
    """Min-cost match (center distance + normal angle) of loops i->j with loops j->i per part pair.
    results: learn_separators outputs ('parent', 'child', 'center', 'pca_normal', ...).
    Returns RLPs {'parts': (i, j), 'a', 'b', 'center', 'normal', 'cost'}, sorted by cost."""
    buckets = defaultdict(lambda: {"A": [], "B": []})  # A: small->large part, B: large->small
    for it in results:
        p, q = int(it["parent"]), int(it["child"])
        if p != q:
            buckets[(min(p, q), max(p, q))]["A" if p < q else "B"].append(it)

    rlps = []
    for (i, j), grp in buckets.items():
        A, B = grp["A"], grp["B"]
        print(f"[info] Pair ({i}, {j}): found {len(A)} loops (i->j) and {len(B)} loops (j->i).")
        if not A or not B:
            continue

        ca = np.array([a["center"] for a in A], dtype=float)
        cb = np.array([b["center"] for b in B], dtype=float)
        na = np.array([loop_normal(a) for a in A])
        nb = np.array([loop_normal(b) for b in B])
        C = w_pos * np.linalg.norm(ca[:, None] - cb[None], axis=2) + w_ang * (1.0 - np.abs(na @ nb.T))
        rows, cols = linear_sum_assignment(C)
        print(f"[info] Pair ({i}, {j}): matched {len(rows)} RLPs.")

        for ia, ib in zip(rows, cols):
            cost = float(C[ia, ib])
            if cost_max is not None and cost > cost_max:
                continue
            n_a, n_b = na[ia], nb[ib]
            if np.dot(n_a, n_b) < 0.0:  # flip if > 90 deg apart
                n_b = -n_b
            rlps.append({
                "parts": (i, j),
                "a": A[ia], "b": B[ib],
                "center": 0.5 * (ca[ia] + cb[ib]),
                "normal": normalize(n_a + n_b) if np.linalg.norm(n_a + n_b) > 1e-9 else n_a,
                "cost": cost,
            })

    rlps.sort(key=lambda d: d["cost"])
    return rlps
