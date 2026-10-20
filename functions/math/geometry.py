import numpy as np


def normalize(v) -> np.ndarray:
    v = np.asarray(v, dtype=float).ravel()
    n = np.linalg.norm(v)
    return v * 0.0 if n < 1e-12 else v / n


def basis_from_normal(n):
    """Orthonormal (u, v, n) with n as the third axis."""
    n = normalize(n)
    axes = np.eye(3)
    k = int(np.argmin(np.abs(axes @ n)))
    u = normalize(np.cross(n, axes[k]))
    v = normalize(np.cross(n, u))
    return u, v, n


def pca_plane(points):
    """Best-fit plane: (centroid, unit normal = least-variance direction)."""
    pts = np.asarray(points, dtype=float)
    c = pts.mean(axis=0)
    X = pts - c
    _, V = np.linalg.eigh(X.T @ X)
    return c, normalize(V[:, 0])


def rotmat(axis, theta: float) -> np.ndarray:
    """Axis-angle rotation matrix (right-handed)."""
    x, y, z = normalize(axis)
    c, s = np.cos(theta), np.sin(theta)
    C = 1.0 - c
    return np.array([
        [c + x*x*C,     x*y*C - z*s, x*z*C + y*s],
        [y*x*C + z*s,   c + y*y*C,   y*z*C - x*s],
        [z*x*C - y*s,   z*y*C + x*s, c + z*z*C]
    ], dtype=float)


def ransac_plane(points, threshold=0.01, iterations=1000) -> np.ndarray:
    """Inlier mask of the largest plane found by RANSAC."""
    n_points = points.shape[0]
    best = np.zeros(n_points, dtype=bool)
    if n_points < 3:
        return best
    for _ in range(iterations):
        p0, p1, p2 = points[np.random.choice(n_points, 3, replace=False)]
        normal = np.cross(p1 - p0, p2 - p0)
        norm = np.linalg.norm(normal)
        if norm < 1e-10:
            continue
        inliers = np.abs((points - p0) @ (normal / norm)) < threshold
        if inliers.sum() > best.sum():
            best = inliers
    return best
