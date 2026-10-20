from collections import Counter, defaultdict, deque

import numpy as np
import trimesh
from scipy.spatial import cKDTree
from trimesh.proximity import signed_distance


# ---------------------------------------------------------------------
# Adjacency & neighborhoods
# ---------------------------------------------------------------------
def adjacency(faces: np.ndarray, num_verts: int) -> list[list[int]]:
    """Vertex adjacency list from triangle faces."""
    adj = [set() for _ in range(num_verts)]
    for a, b, c in faces.astype(np.int64, copy=False):
        adj[a].update((b, c)); adj[b].update((a, c)); adj[c].update((a, b))
    return [list(s) for s in adj]


def k_hop(adj, seeds, max_hops: int = 5):
    """BFS from seeds. Returns (vertices with hop < max_hops, hop distance per vertex)."""
    INF = max_hops + 1
    dist = np.full(len(adj), INF, dtype=np.int32)
    dist[list(seeds)] = 0
    q = deque(seeds)
    while q:
        u = q.popleft()
        if dist[u] + 1 >= max_hops:
            continue
        for v in adj[u]:
            if dist[v] == INF:
                dist[v] = dist[u] + 1
                q.append(v)
    return np.nonzero(dist < max_hops)[0], dist


# ---------------------------------------------------------------------
# Vertex labeling
# ---------------------------------------------------------------------
def label_vertices(verts: np.ndarray,
                   categories: list[list[trimesh.Trimesh]],
                   use_signed_dist: bool = True,
                   sdf_thresh: float = 0.0,
                   batch_size: int = 50000,
                   k_vote: int = 3) -> np.ndarray:
    """Label each vertex with the category whose part meshes contain it (-1 = none).
    Leftover vertices take a k-nearest-labeled-neighbor majority vote (tie: smallest distance sum)."""
    vert_label = -np.ones(len(verts), dtype=np.int32)
    best_sd = np.full(len(verts), np.inf, dtype=np.float32)

    for cid, meshes in enumerate(categories):
        for pm in meshes:
            in_box = np.all((verts >= pm.vertices.min(axis=0)) & (verts <= pm.vertices.max(axis=0)), axis=1)
            idx = np.nonzero(in_box)[0]
            for s in range(0, idx.size, batch_size):
                take = idx[s:s + batch_size]
                if use_signed_dist:
                    sd = -signed_distance(pm, verts[take]).astype(np.float32)  # negative = inside
                    upd = (sd <= sdf_thresh) & (sd < best_sd[take])
                    best_sd[take[upd]] = sd[upd]
                else:
                    upd = pm.contains(verts[take]) & (vert_label[take] == -1)
                vert_label[take[upd]] = cid

    unlabeled = np.nonzero(vert_label == -1)[0]
    labeled = np.nonzero(vert_label >= 0)[0]
    if unlabeled.size == 0 or labeled.size == 0:
        return vert_label

    k = int(min(k_vote, labeled.size))
    dists, idxs = cKDTree(verts[labeled]).query(verts[unlabeled], k=k, workers=-1)
    dists = dists.reshape(len(unlabeled), k)
    labs = vert_label[labeled[idxs.reshape(len(unlabeled), k)]]
    for m, u in enumerate(unlabeled):
        vals, cnts = np.unique(labs[m], return_counts=True)
        cand = vals[cnts == cnts.max()]
        vert_label[u] = min(cand, key=lambda L: dists[m][labs[m] == L].sum())
    return vert_label


# ---------------------------------------------------------------------
# Boundary loops
# ---------------------------------------------------------------------
def mesh_boundary_loops(t_mesh: trimesh.Trimesh) -> list:
    """All boundary loops (vertex index lists) of a mesh: chains of edges used by one face."""
    unique_edges, counts = np.unique(t_mesh.edges_sorted, axis=0, return_counts=True)
    boundary_edges = unique_edges[counts == 1]
    if len(boundary_edges) == 0:
        return []
    neighbours = defaultdict(list)
    for v1, v2 in boundary_edges:
        neighbours[v1].append(v2); neighbours[v2].append(v1)

    loops = []
    remaining = set(map(tuple, boundary_edges))
    while remaining:
        v_start, v_next = remaining.pop()
        loop = [v_start, v_next]
        while v_next != v_start:
            options = neighbours[v_next]
            if len(options) != 2:
                break
            v_next = options[1] if options[0] == loop[-2] else options[0]
            if v_next == v_start:
                break
            loop.append(v_next)
        for a, b in zip(loop, loop[1:] + loop[:1]):
            remaining.discard(tuple(sorted((a, b))))
        loops.append(loop)
    return loops


def part_boundary_loops(faces: np.ndarray,
                        part_indices: np.ndarray,
                        min_len: int = 4,
                        open_loop_threshold: int = 10,
                        min_new_edge_frac: float = 0.25) -> list[np.ndarray]:
    """Boundary loops of the faces fully inside `part_indices`, walked by face winding.
    Loops are taken longest first; a loop is kept only if >= min_new_edge_frac of its edges are new."""
    sub_faces = faces[np.isin(faces, part_indices).all(axis=1)]
    if sub_faces.size == 0:
        return []

    edges = np.concatenate([sub_faces[:, [0, 1]], sub_faces[:, [1, 2]], sub_faces[:, [2, 0]]])
    directed = set(map(tuple, np.unique(edges, axis=0).tolist()))  # sorted insert keeps walk order stable
    boundary_edges = [(u, v) for u, v in directed if (v, u) not in directed]  # (v, u) missing => boundary
    if not boundary_edges:
        return []
    out_edges = defaultdict(list)
    for u, v in boundary_edges:
        out_edges[u].append(v)

    # Walk paths
    walked = set()
    candidates = []  # (path, is_closed)
    for start in list(out_edges):
        if all((start, nxt) in walked for nxt in out_edges[start]):
            continue
        curr, path = start, [start]
        while True:
            nxt = next((n for n in out_edges[curr] if (curr, n) not in walked), None)
            if nxt is None:  # dead end -> open loop
                if len(path) >= open_loop_threshold:
                    candidates.append((np.array(path, dtype=int), False))
                break
            walked.add((curr, nxt))
            curr = nxt
            path.append(curr)
            if curr == path[0]:  # cycle -> closed loop
                if len(path) - 1 >= min_len:
                    candidates.append((np.array(path[:-1], dtype=int), True))
                break
            if len(path) > len(boundary_edges) + 1:  # safety brake
                break

    # Longest first, keep loops that add enough unseen edges
    candidates.sort(key=lambda x: len(x[0]), reverse=True)
    selected, used = [], set()
    for path, is_closed in candidates:
        ends = np.roll(path, -1) if is_closed else path[1:]
        edges_k = {(min(u, v), max(u, v)) for u, v in zip(path, ends)}
        if edges_k and len(edges_k - used) / len(edges_k) >= min_new_edge_frac:
            selected.append(path)
            used |= edges_k
    return selected


def merge_loops(adj, loops: list[np.ndarray], max_hops: int = 2, min_size: int = 10) -> list[np.ndarray]:
    """Merge loops within max_hops edges of each other; drop merged loops smaller than min_size.
    Merged loops are unordered vertex sets (fine for PCA/SVM). Sorted largest first."""
    if not loops:
        return []
    loop_sets = [set(l) for l in loops]
    reach = [set(k_hop(adj, l, max_hops + 1)[0].tolist()) for l in loops]

    n = len(loops)
    meta_adj = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if not loop_sets[j].isdisjoint(reach[i]) or not loop_sets[i].isdisjoint(reach[j]):
                meta_adj[i].append(j); meta_adj[j].append(i)

    visited = [False] * n
    merged = []
    for i in range(n):
        if visited[i]:
            continue
        comp, stack = [], [i]
        visited[i] = True
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nb in meta_adj[cur]:
                if not visited[nb]:
                    visited[nb] = True
                    stack.append(nb)
        loop = loops[comp[0]] if len(comp) == 1 else np.unique(np.concatenate([loops[c] for c in comp]))
        if len(loop) >= min_size:
            merged.append(loop)
    merged.sort(key=len, reverse=True)
    return merged


def loop_neighbors(loop, adj, vert_label: np.ndarray, parent: int, threshold: float = 0.25) -> list[int]:
    """Part labels touching the loop with share >= threshold (else the most frequent one)."""
    counts = Counter(int(vert_label[v]) for u in loop for v in adj[u])
    counts = Counter({l: c for l, c in counts.items() if l > 0 and l != parent})  # skip background & parent
    if not counts:
        return []
    total = sum(counts.values())
    return [l for l, c in counts.items() if c / total >= threshold] or [counts.most_common(1)[0][0]]
