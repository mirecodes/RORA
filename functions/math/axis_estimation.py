"""Axis estimation: separating planes between a part and its neighbors around each boundary cycle."""
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC, SVC

from functions.math.geometry import pca_plane
from functions.math.graph import cycle_neighbors, k_hop, merge_cycles, part_boundary_cycles
from functions.visualize.plots import show_axis_estimation, show_cycles
from functions.visualize.style import pastel_hex


def _to_world_plane(w_s, b_s, scaler):
    """Hyperplane in scaled space -> (unit normal n, offset d) in world space."""
    w = w_s / scaler.scale_
    b = b_s - np.dot(w, scaler.mean_)
    norm = np.linalg.norm(w) + 1e-12
    return w / norm, b / norm


def margin_score(clf, Xs, y) -> float:
    return float(np.mean(y * clf.decision_function(Xs)))


# -----------------------------------------------------------------------------
# Trainers
# -----------------------------------------------------------------------------
def train_svm(verts, idx_pos, idx_neg, kernel: str = "linear", C: float = 1.0,
              gamma: str | float = "scale", balance: str = "downsample", random_state: int | None = 0):
    """Linear or RBF SVM on positive/negative vertices. balance: 'downsample' | 'weights' | 'none'."""
    pos, neg = np.unique(idx_pos), np.unique(idx_neg)
    if len(pos) == 0 or len(neg) == 0:
        raise ValueError("Not enough positive/negative samples for SVM.")
    if balance == "downsample":
        rng = np.random.default_rng(random_state)
        k = min(len(pos), len(neg))
        pos, neg = rng.choice(pos, k, replace=False), rng.choice(neg, k, replace=False)

    X = np.vstack([verts[pos], verts[neg]])
    y = np.hstack([np.ones(len(pos)), -np.ones(len(neg))])
    scaler = StandardScaler().fit(X)

    class_w = "balanced" if balance in ("weights", "downsample") else None
    if kernel == "linear":
        clf = LinearSVC(C=C, class_weight=class_w, max_iter=5000)
    elif kernel == "rbf":
        clf = SVC(kernel="rbf", C=C, gamma=gamma, class_weight=class_w, random_state=random_state)
    else:
        raise ValueError(f"Undefined SVM kernel: {kernel}")
    clf.fit(scaler.transform(X), y)
    return clf, scaler


def train_multi_plane(verts, idx_pos, idx_neg, K: int = 2, max_iter: int = 20, C: float = 1.0,
                      random_state: int = 0, boundary: str = "auto", reinit_when_empty: bool = True) -> dict:
    """K linear planes whose AND (convex) or OR (concave) region holds the positives, trained by EM.
    boundary: 'convex' | 'concave' | 'auto' (best of both). Returns {'planes': [(n, d)], 'scaler', 'boundary', 'score'}."""
    rng = np.random.default_rng(random_state)
    Xp, Xn = verts[np.unique(idx_pos)], verts[np.unique(idx_neg)]
    scaler = StandardScaler().fit(np.vstack([Xp, Xn]))
    Xp_s, Xn_s = scaler.transform(Xp), scaler.transform(Xn)

    def svc(pos, neg):
        clf = LinearSVC(C=C, class_weight="balanced", max_iter=3000, random_state=random_state)
        clf.fit(np.vstack([pos, neg]), np.hstack([np.ones(len(pos)), -np.ones(len(neg))]))
        return clf.coef_.ravel(), clf.intercept_[0]

    def init_weights(bd):
        # convex: cluster negatives into K directions; concave: cluster positives into K branches
        side = Xn_s if bd == "convex" else Xp_s
        try:
            if len(side) >= K:
                labels = KMeans(n_clusters=K, random_state=random_state, n_init=5).fit_predict(side)
                Wb = []
                for j in range(K):
                    sub = side[labels == j] if np.any(labels == j) else side
                    Wb.append(svc(Xp_s, sub) if bd == "convex" else svc(sub, Xn_s))
                W, b = map(np.array, zip(*Wb))
                return W.astype(np.float64), b.astype(np.float64)
        except Exception:
            pass
        # Fallback: one LinearSVC copied K times + jitter
        w0, b0 = svc(Xp_s, Xn_s)
        W = np.tile(w0, (K, 1)).astype(np.float64)
        b = np.tile(b0, K).astype(np.float64)
        W += 0.05 * rng.standard_normal(W.shape)
        b += 0.05 * rng.standard_normal(b.shape)
        return W, b

    def em(bd):
        W, b = init_weights(bd)
        assign_pos = assign_neg = [np.array([], dtype=int)] * K
        for _ in range(max_iter):
            # E-step. convex : every positive in all planes, each negative to its highest-scoring plane.
            #         concave: each positive to its highest-scoring plane, every negative in all planes.
            if bd == "convex":
                new_pos = [np.arange(len(Xp_s))] * K
                j_neg = np.argmax(Xn_s @ W.T + b, axis=1)
                new_neg = [np.nonzero(j_neg == j)[0] for j in range(K)]
            else:
                j_pos = np.argmax(Xp_s @ W.T + b, axis=1)
                new_pos = [np.nonzero(j_pos == j)[0] for j in range(K)]
                new_neg = [np.arange(len(Xn_s))] * K
            converged = all(map(np.array_equal, assign_neg, new_neg)) and all(map(np.array_equal, assign_pos, new_pos))
            assign_pos, assign_neg = new_pos, new_neg
            if converged:
                break
            # M-step
            for j in range(K):
                if assign_pos[j].size == 0 or assign_neg[j].size == 0:
                    if reinit_when_empty:
                        W[j] += 0.02 * rng.standard_normal(W[j].shape)
                        b[j] += 0.02 * rng.standard_normal(())
                    continue
                W[j], b[j] = svc(Xp_s[assign_pos[j]], Xn_s[assign_neg[j]])
        return W, b

    def score(W, b, bd):
        """Balanced accuracy + tiny margin bonus."""
        y = np.hstack([np.ones(len(Xp_s)), -np.ones(len(Xn_s))]).astype(int)
        S = np.vstack([Xp_s, Xn_s]) @ W.T + b
        s = S.min(axis=1) if bd == "convex" else S.max(axis=1)
        pred = np.where(s > 0.0, 1, -1)
        pos_acc = float(np.mean(pred[y == 1] == 1)) if len(Xp_s) else 0.0
        neg_acc = float(np.mean(pred[y == -1] == -1)) if len(Xn_s) else 0.0
        return 0.5 * (pos_acc + neg_acc) + 1e-4 * float(np.mean(y * s))

    if boundary in ("convex", "concave"):
        W, b = em(boundary)
    elif boundary == "auto":
        fits = {bd: em(bd) for bd in ("convex", "concave")}
        boundary = "convex" if score(*fits["convex"], "convex") >= score(*fits["concave"], "concave") else "concave"
        W, b = fits[boundary]
    else:
        raise ValueError(f"Unknown boundary: {boundary}")

    return {
        "planes": [_to_world_plane(W[j], b[j], scaler) for j in range(K)],
        "scaler": scaler,
        "boundary": boundary,
        "score": score(W, b, boundary),
    }


# -----------------------------------------------------------------------------
# Per-part entry
# -----------------------------------------------------------------------------
def estimate_unicons(verts: np.ndarray,
                     faces: np.ndarray,
                     idx_part: int,
                     adj,
                     vert_label: np.ndarray,
                     max_hops: int = 5,
                     method: str | list[str] = "all",  # 'single_plane' | 'rbf' | 'multi_plane' | 'all' | list
                     C: float = 1.0,
                     gamma: str | float = "scale",
                     balance: str = "downsample",      # 'downsample' | 'weights' | 'none'
                     random_state: int | None = 0,
                     visualize_results: bool = False,
                     neighbor_threshold: float = 0.25,
                     min_size_to_keep: int = 5,
                     show_none_cycles: bool = False) -> list[dict]:
    """For each boundary cycle of part `idx_part`, estimate planes against the touching part(s).
    Returns one unidirectional connection (unicon) per (cycle, neighbor part)."""
    print(f"[info] Estimating axes for part {idx_part}...")
    faces = faces.astype(np.int64)
    idx_seeds = np.nonzero(vert_label == idx_part)[0]
    if len(idx_seeds) == 0:
        raise RuntimeError("[error]: Target part has no included vertices. Check watertight/SDF settings.")

    # Boundary cycles; cycles within 2 hops count as one boundary
    cycles = part_boundary_cycles(faces, idx_seeds)
    print(f"[debug] Raw cycles: {len(cycles)} (sizes: {[len(c) for c in cycles]})")
    cycles = merge_cycles(adj, cycles, max_hops=2, min_size=min_size_to_keep)
    print(f"[info] Found {len(cycles)} cycles for part {idx_part}.")

    nbrs_per_cycle = [cycle_neighbors(c, adj, vert_label, idx_part, neighbor_threshold) for c in cycles]
    if visualize_results and cycles:
        show_cycles(verts, faces, cycles, nbrs_per_cycle, idx_part, vert_label=vert_label,
                    title=f"All Boundary Cycles for Part {idx_part}", show_none_cycles=show_none_cycles)

    methods = list(method) if isinstance(method, (list, tuple)) else \
        ["single_plane", "rbf", "multi_plane"] if method == "all" else [str(method)]

    unicons = []
    for order, (cycle, nbrs) in enumerate(zip(cycles, nbrs_per_cycle)):
        print(f"[info] Processing cycle {order + 1}/{len(cycles)} (size: {len(cycle)})...")
        # Positives: own part, negatives: other parts, within max_hops of the cycle
        idx_neighbor, dist = k_hop(adj, cycle, max_hops)
        lab = vert_label[idx_neighbor]
        idx_pos = idx_neighbor[lab == idx_part]
        idx_neg = idx_neighbor[(lab > 0) & (lab != idx_part)]

        if not nbrs:
            print(f"[warn] cycle {order} has no valid neighbors.")
            continue
        cycle_idx = np.asarray(cycle, dtype=int).ravel()
        center, pca_normal = pca_plane(verts[cycle_idx])
        if len(idx_pos) == 0 or len(idx_neg) == 0:
            print(f"[warn] cycle {order} skipped (not enough pos/neg).")
            continue

        print(f"[info] Estimating planes for cycle {order + 1}...")
        X = np.vstack([verts[idx_pos], verts[idx_neg]])
        y = np.hstack([np.ones(len(idx_pos)), -np.ones(len(idx_neg))]).astype(int)
        fits = {}
        for m, kernel in (("single_plane", "linear"), ("rbf", "rbf")):
            if m in methods:
                clf, scaler = train_svm(verts, idx_pos, idx_neg, kernel=kernel, C=C, gamma=gamma,
                                        balance=balance, random_state=random_state)
                plane = [_to_world_plane(clf.coef_.ravel(), clf.intercept_[0], scaler)] if kernel == "linear" else []
                fits[m] = {"method": m, "clf": clf, "scaler": scaler, "plane": plane,
                           "score": margin_score(clf, scaler.transform(X), y)}
        if "multi_plane" in methods:
            multi = train_multi_plane(verts, idx_pos, idx_neg, K=2, C=C, random_state=random_state)
            fits["multi_plane"] = {"method": "multi_plane", "clf": None, "scaler": multi["scaler"],
                                   "plane": multi["planes"], "score": multi["score"]}

        if visualize_results:
            cycle_color = pastel_hex(nbrs[0] if isinstance(nbrs[0], int) else idx_part)
            for m in methods:
                if fits.get(m, {}).get("plane"):
                    show_axis_estimation(verts, faces, idx_pos, idx_neg, fits[m]["plane"], center,
                                         title=f"Cycle {order + 1}, Method: {m}", cycle_indices=cycle_idx,
                                         idx_part=idx_part, cycle_color=cycle_color)

        # One unicon per neighbor part
        for nbr in nbrs:
            unicons.append({
                "src": idx_part, "dst": nbr, "cycle": cycle,
                "center": center, "pca_normal": pca_normal, "vert_label": vert_label,
                "idx_pos": idx_pos, "idx_neg": idx_neg, "idx_neighbor": idx_neighbor, "dist": dist,
                "single_plane": fits.get("single_plane", {}), "rbf": fits.get("rbf", {}),
                "multi_plane": fits.get("multi_plane", {}),
            })

    print(f"[info] Part {idx_part}: {len(unicons)} unicons.")
    return unicons
