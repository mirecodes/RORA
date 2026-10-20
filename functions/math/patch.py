"""Fill a boundary cycle with a smooth triangulated patch (cycle projected to its PCA plane)."""
import matplotlib.tri as mtri
import numpy as np

from functions.math.geometry import basis_from_normal, pca_plane


# ---------------------------------------------------------------------
# 2D helpers (uv = cycle plane coordinates)
# ---------------------------------------------------------------------
def in_polygon(poly_uv: np.ndarray, pts_uv: np.ndarray) -> np.ndarray:
    """Ray-casting point-in-polygon test."""
    x, y = pts_uv[:, 0], pts_uv[:, 1]
    inside = np.zeros(len(pts_uv), dtype=bool)
    j = len(poly_uv) - 1
    for i in range(len(poly_uv)):
        (xi, yi), (xj, yj) = poly_uv[i], poly_uv[j]
        inside ^= ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi)
        j = i
    return inside


def project_to_segment(P: np.ndarray, A: np.ndarray, B: np.ndarray):
    """Project points onto segment A->B. Returns (proj, t, squared distance)."""
    AB = B - A
    t = np.clip(((P - A) @ AB) / ((AB @ AB) + 1e-12), 0.0, 1.0)
    proj = A + t[:, None] * AB
    return proj, t, np.sum((P - proj) ** 2, axis=1)


def _closed(poly_uv: np.ndarray) -> bool:
    return poly_uv.shape[0] >= 2 and np.allclose(poly_uv[0], poly_uv[-1])


def boundary_height(pts_uv: np.ndarray, poly_uv: np.ndarray, h_cycle: np.ndarray):
    """Distance to the cycle polyline and the cycle height interpolated at the closest point."""
    if poly_uv.shape[0] >= 2 and not _closed(poly_uv):
        poly_uv = np.vstack([poly_uv, poly_uv[0]])
        h_cycle = np.concatenate([h_cycle, h_cycle[:1]])
    dist2 = np.full(len(pts_uv), np.inf)
    hb = np.zeros(len(pts_uv))
    for i in range(len(poly_uv) - 1):
        _, t, d2 = project_to_segment(pts_uv, poly_uv[i], poly_uv[i + 1])
        upd = d2 < dist2
        dist2[upd] = d2[upd]
        hb[upd] = (1.0 - t[upd]) * h_cycle[i] + t[upd] * h_cycle[i + 1]
    return np.sqrt(dist2), hb


def densify_cycle(poly_uv: np.ndarray, step: float) -> np.ndarray:
    """Closed polyline with extra samples every ~step along each edge."""
    poly_uv = np.asarray(poly_uv, dtype=float)
    if poly_uv.shape[0] >= 2 and not _closed(poly_uv):
        poly_uv = np.vstack([poly_uv, poly_uv[0]])
    pts = [poly_uv[0]]
    for a, b in zip(poly_uv[:-1], poly_uv[1:]):
        L = float(np.linalg.norm(b - a))
        if L <= 1e-12:
            continue
        nadd = max(0, int(np.ceil(L / max(step, 1e-12))) - 1)
        pts.extend(a + (t / (nadd + 1)) * (b - a) for t in range(1, nadd + 1))
        pts.append(b)
    return np.asarray(pts, dtype=float)


def delaunay_2d(pts_uv: np.ndarray):
    """matplotlib Delaunay triangulation, or None if degenerate."""
    if pts_uv.shape[0] < 3:
        return None
    tri = mtri.Triangulation(pts_uv[:, 0], pts_uv[:, 1])
    return tri if tri.triangles.size else None


# ---------------------------------------------------------------------
# Height interpolation
# ---------------------------------------------------------------------
def harmonic_heights(pts_uv, triangles, boundary_mask, h_boundary, *,
                     alpha: float = 0.5, weight_clip: float = 10.0,
                     max_iters: int = 1000, tol: float = 1e-6) -> np.ndarray:
    """Value-weighted Jacobi solve of Laplacian(H) = 0 with fixed boundary heights."""
    N = pts_uv.shape[0]
    neighbors = [set() for _ in range(N)]
    for a, b, c in np.asarray(triangles, dtype=int):
        neighbors[a].update((b, c)); neighbors[b].update((a, c)); neighbors[c].update((a, b))

    H = np.zeros(N)
    H[boundary_mask] = h_boundary[boundary_mask]
    interior = np.nonzero(~boundary_mask)[0]
    if interior.size == 0:
        return H

    H_new = H.copy()
    for _ in range(max_iters):
        max_delta = 0.0
        for i in interior:
            if not neighbors[i]:
                continue
            Hj = H[list(neighbors[i])]
            w = 1.0 + alpha * np.minimum(np.abs(Hj), weight_clip)
            v = float(w @ Hj / w.sum())
            max_delta = max(max_delta, abs(v - H[i]))
            H_new[i] = v
        H, H_new = H_new, H
        if max_delta < tol:
            break
    return H


def radius_update(idx, pts_uv, H, known, sigma, k_min, radius) -> bool:
    """Set H[idx] to the Gaussian-weighted mean of known neighbors within radius."""
    d = np.sqrt(np.sum((pts_uv - pts_uv[idx]) ** 2, axis=1))
    cand = np.nonzero((d > 0) & (d <= radius))[0]
    kk = cand[known[cand]]
    if kk.size < k_min:
        return False
    w = np.exp(-(d[kk] ** 2) / (2.0 * sigma * sigma))
    if w.sum() <= 1e-12:
        return False
    H[idx] = float(np.sum(w * H[kk]) / w.sum())
    return True


# ---------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------
def cycle_patch(cycle_xyz, *, step_rel: float = 0.01, sigma_scale: float = 2.0, k_min: int = 6):
    """Triangulated patch filling a 3D cycle. Returns (vertices (N,3), faces (M,3))."""
    empty = np.zeros((0, 3), dtype=float), np.zeros((0, 3), dtype=int)
    cycle_xyz = np.asarray(cycle_xyz, dtype=float)
    if cycle_xyz.shape[0] < 3:
        return empty

    c, n = pca_plane(cycle_xyz)
    u, v, n = basis_from_normal(n)
    rel = cycle_xyz - c
    poly_uv = np.column_stack([rel @ u, rel @ v])
    poly_open = poly_uv[:-1] if _closed(poly_uv) else poly_uv

    bb_min, bb_max = poly_uv.min(axis=0), poly_uv.max(axis=0)
    diag = float(np.linalg.norm(bb_max - bb_min))
    if diag <= 0:
        return empty
    step = max(diag * step_rel, 1e-6)

    # Grid points inside the cycle + densified cycle as boundary
    nx = max(1, int(np.ceil((bb_max[0] - bb_min[0]) / step))) + 1
    ny = max(1, int(np.ceil((bb_max[1] - bb_min[1]) / step))) + 1
    GX, GY = np.meshgrid(np.linspace(bb_min[0], bb_max[0], nx), np.linspace(bb_min[1], bb_max[1], ny))
    grid_uv = np.column_stack([GX.ravel(), GY.ravel()])
    pts_inside = grid_uv[in_polygon(poly_open, grid_uv)]
    if pts_inside.size == 0:
        return empty

    dense_boundary = densify_cycle(poly_uv, step)
    h_cycle = rel @ n
    _, hb_dense = boundary_height(dense_boundary, poly_uv, h_cycle)

    pts_uv = np.vstack([pts_inside, dense_boundary])
    M_in, M_bd = pts_inside.shape[0], dense_boundary.shape[0]
    to_xyz = lambda H: c + np.outer(pts_uv[:, 0], u) + np.outer(pts_uv[:, 1], v) + np.outer(H, n)

    tri = delaunay_2d(pts_uv)
    if tri is None:
        # No triangulation: propagate heights inward from the boundary (points only)
        dist_in, hb_in = boundary_height(pts_inside, poly_uv, h_cycle)
        dist = np.concatenate([dist_in, np.zeros(M_bd)])
        hb = np.concatenate([hb_in, hb_dense])
        H = np.full(pts_uv.shape[0], np.nan)
        is_in = np.arange(pts_uv.shape[0]) < M_in
        known = ~is_in | (dist <= step * 0.75)
        H[known] = hb[known]
        sigma = max(step * sigma_scale, 1e-9)
        for idx in np.argsort(dist[:M_in]):
            if not known[idx]:
                known[idx] = radius_update(idx, pts_uv, H, known, sigma, k_min, 3.0 * sigma)
        pend = np.nonzero(~known[:M_in])[0]
        H[pend] = hb[:M_in][pend]
        return to_xyz(H), empty[1]

    boundary_mask = np.zeros(pts_uv.shape[0], dtype=bool)
    boundary_mask[M_in:] = True
    hB = np.zeros(pts_uv.shape[0])
    hB[M_in:] = hb_dense
    H = harmonic_heights(pts_uv, tri.triangles, boundary_mask, hB)

    # Keep triangles whose centroid is inside the cycle
    tris = np.asarray(tri.triangles, dtype=int)
    inside = in_polygon(poly_open, pts_uv[tris].mean(axis=1))
    return to_xyz(H), tris[inside]
