import os
import numpy as np
import pymeshlab
import trimesh
from typing import Dict, List, Tuple
from collections import defaultdict

from json_handler import JsonHandler
from functions.math.geometry import normalize
from functions.math.graph import adjacency, label_vertices
from functions.math.patch import loop_patch
from functions.math.rlp import cluster_rlps, loop_normal, merge_lines, plane_intersections
from functions.math.separator import learn_separators
from functions.utils.mesh import append_patches, save_link_meshes
from functions.utils.urdf import joints_from_rlps
from functions.visualize.plots import show_labels, show_rlps
from functions.visualize.select import select_joint_vectors, select_parts


# =============================================================================
# Pipeline helpers (separation, vectors, patches)
# =============================================================================
def compute_separation_results(verts, faces, categories_num: int, adj, vert_label,
                               visualize_results: bool = False, **separator_kwargs) -> List[dict]:
    """Run learn_separators per category and flatten outputs."""
    print(f"[info] Starting separation computation for {categories_num} categories...")
    results_list = []
    for idx_part in range(1, categories_num + 1):
        print(f"[info] Processing category {idx_part}/{categories_num}...")
        results_list += learn_separators(verts, faces, idx_part, adj, vert_label,
                                         visualize_results=visualize_results, **separator_kwargs)
    print(f"[info] Separation computation finished. Total results: {len(results_list)}")
    return results_list


def prepare_vectors_for_rlps(rlps: List[dict]) -> None:
    """Create vector candidates on each RLP from plane/normal info."""
    print(f"[info] Preparing vectors for {len(rlps)} RLPs...")
    for rlp in rlps:
        center = rlp['center']
        # Use the RLP normal computed in cluster_rlps directly
        n_plane = np.asarray(rlp["normal"], dtype=float)
        
        A = rlp['a']['linear']; B = rlp['b']['linear']
        dA = float(A['plane'][0][1]) if A.get('plane') and len(A['plane']) > 0 else 0.0
        dB = float(B['plane'][0][1]) if B.get('plane') and len(B['plane']) > 0 else 0.0
        d_plane = 0.5 * (dA + dB)
        
        # 1. Add the main linear normal vector candidate (as list)
        rlp['vectors'] = [{
            'center': center if isinstance(center, list) else center.tolist(),
            'n': n_plane.tolist(),
            'd': d_plane.tolist() if isinstance(d_plane, np.ndarray) else d_plane,
            'type': 'normal'
        }]

        # 2-3. Polyhedral intersection lines from BOTH directions, matched and merged
        merged_lines = merge_lines(plane_intersections(rlp['a'].get('polyhedral', {}).get('plane') or []),
                                   plane_intersections(rlp['b'].get('polyhedral', {}).get('plane') or []))

        # 4. Add the first merged intersection line & the 3rd recommended vector
        if len(merged_lines) > 0:
            line = merged_lines[0]
            # Add intersection line candidate
            rlp['vectors'].append({
                'center': center if isinstance(center, list) else center.tolist(),
                'n': line.tolist(),
                'd': [0.0, 0.0, 0.0],
                'type': 'intersection'
            })
            
            # Add 3rd vector (perpendicular to both main plane normal and the intersection line)
            n_third = np.cross(n_plane, line)
            if np.linalg.norm(n_third) > 1e-6:
                rlp['vectors'].append({
                    'center': center if isinstance(center, list) else center.tolist(),
                    'n': normalize(n_third).tolist(),
                    'd': [0.0, 0.0, 0.0],
                    'type': 'cross'
                })
                
    print("[info] Vector preparation finished.")


def build_extrapoints_and_patches(results_list: List[dict],
                                  verts: np.ndarray):
    """For each loop: dense sampling + triangulated patch."""
    print("[info] Building extra points and patches...")
    patch_vertices: Dict[int, List[np.ndarray]] = defaultdict(list)
    patch_faces: Dict[int, List[np.ndarray]] = defaultdict(list)
    for res in results_list:
        pid = int(res.get('parent', 0))
        loop_idx = res.get('loop', None)
        if pid <= 0 or loop_idx is None or len(loop_idx) < 3:
            continue
        loop_xyz = verts[np.asarray(loop_idx, dtype=int)]
        P3, F = loop_patch(loop_xyz, step_rel=0.03, sigma_scale=2.0, k_min=6)
        if P3.size and F.size:
            patch_vertices[pid].append(P3.astype(float))
            patch_faces[pid].append(F.astype(np.int64))
    print("[info] Patch building finished.")
    return patch_vertices, patch_faces


def append_single_loop_rlps(results_list: List[dict], rlps: List[dict], verts: np.ndarray) -> None:
    """Find (i, j) part pairs that have 1 loop on one side and 0 on the other, and add them as RLPs."""
    print("[info] Checking for single-loop RLPs (1-0 cases)...")
    pair_to_res = defaultdict(list)
    for res in results_list:
        p = res.get('parent', -1)
        c = res.get('child', -1)
        if p != -1 and c != -1:
            pair_to_res[(p, c)].append(res)
    
    checked = set()
    count = 0
    for (p, c) in pair_to_res.keys():
        key = tuple(sorted([p, c]))
        if key in checked: continue
        checked.add(key)
        
        p1, p2 = key
        loops_12 = pair_to_res.get((p1, p2), [])
        loops_21 = pair_to_res.get((p2, p1), [])
        
        # Exactly one loop in one direction (1,0) or (0,1)
        if (len(loops_12) == 1 and len(loops_21) == 0) or (len(loops_12) == 0 and len(loops_21) == 1):
            single = loops_12[0] if len(loops_12) == 1 else loops_21[0]
            
            already_in = False
            for r in rlps:
                if r.get('a') is single or r.get('b') is single:
                    already_in = True
                    break
            
            if not already_in:
                loop_idx = single.get('loop', [])
                if len(loop_idx) > 0:
                    center = np.mean(verts[np.asarray(loop_idx, dtype=int)], axis=0)
                else:
                    center = np.zeros(3)
                
                n_val = loop_normal(single)
                rlp = {
                    'parts': key,
                    'a': single,
                    'b': single,  # duplicate into b so downstream code doesn't break
                    'center': center.tolist(),
                    'normal': n_val.tolist(),
                    'cost': 0.0,
                    'parent': single.get('parent', -1),
                    'child': single.get('child', -1),
                    'is_single': True
                }
                rlps.append(rlp)
                count += 1
    
    if count > 0:
        print(f"[info] Appended {count} single-loop RLP(s).")


# =============================================================================
# Link-pair utilities (used for augmentation only)
# =============================================================================
def build_link_map(rlps: List[dict]) -> Dict[Tuple[int, int], List[int]]:
    """(i,j)(i<j) -> indices of RLPs connecting the two parts."""
    link_map: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for idx, r in enumerate(rlps):
        p = int(r.get("a", {}).get("parent", r.get("parent", -1)))
        c = int(r.get("a", {}).get("child",  r.get("child",  -1)))
        if p < 0 or c < 0 or p == c:
            continue
        key = (p, c) if p < c else (c, p)
        link_map[key].append(idx)
    return link_map


def pick_normal_from_rlp(rlp: dict) -> np.ndarray | None:
    """Try RLP normal first, then fallback to single loop plane/PCA normal."""
    if "normal" in rlp:
        n = np.asarray(rlp["normal"], dtype=float)
        if np.isfinite(n).all() and np.linalg.norm(n) > 1e-12:
            return normalize(n)
            
    plane = rlp.get("linear", {}).get("plane", None)
    if plane and len(plane) >= 1 and len(plane[0]) >= 1:
        n = np.asarray(plane[0][0], dtype=float)
        if np.isfinite(n).all() and np.linalg.norm(n) > 1e-12:
            return normalize(n)
    n = np.asarray(rlp.get("pca_normal", None), dtype=float) if rlp.get("pca_normal", None) is not None else None
    if n is None or not np.isfinite(n).all() or np.linalg.norm(n) < 1e-12:
        return None
    return normalize(n)


def augment_for_group(rlps: List[dict], group_indices: List[int]) -> None:
    """Add a pair-level vector suggestion into each RLP in the group."""
    if len(group_indices) < 2:
        return
    centers, normals, weights = [], [], []
    for i in group_indices:
        r = rlps[i]
        ctr = np.asarray(r.get("center", None), dtype=float)
        nrm = pick_normal_from_rlp(r)
        if ctr is None or ctr.size != 3 or not np.isfinite(ctr).all():
            continue
        centers.append(ctr); normals.append(nrm)
        loop_idx = r.get("loop", [])
        w = int(len(loop_idx)) if loop_idx is not None else 1
        weights.append(max(w, 1))

    if len(centers) < 2:
        return

    if len(group_indices) == 2:
        c1, c2 = centers[0], centers[1]
        start = 0.5 * (c1 + c2)
        diff = c2 - c1
        if np.linalg.norm(diff) > 1e-6:
            dirv = normalize(diff)
        else:
            n1 = normals[0] if normals[0] is not None else np.array([0.0, 0.0, 1.0])
            n2 = normals[1] if normals[1] is not None else np.array([0.0, 0.0, 1.0])
            if np.dot(n1, n2) < 0:
                n2 = -n2
            dirv = normalize(n1 + n2)
        vec = {"center": start.astype(float).tolist(), "n": dirv.astype(float).tolist(),
               "state": "None", "source": "pair2", "type": "intersection"}
        first_rlp = rlps[group_indices[0]]
        first_rlp.setdefault("vectors", [])
        first_rlp["vectors"].append(dict(vec))
        return

    # 3 or more RLPs
    C = np.vstack(centers)
    start = C.mean(axis=0)
    Ns = [n for n in normals if n is not None]
    if Ns:
        N = np.vstack(Ns)
        ref = N[0]
        for k in range(len(N)):
            if np.dot(N[k], ref) < 0:
                N[k] = -N[k]
        navg = normalize(N.sum(axis=0))
    else:
        X = C - C.mean(axis=0)
        _, _, Vt = np.linalg.svd(X, full_matrices=False)
        navg = normalize(Vt[0])

    vec = {"center": start.astype(float).tolist(), "n": navg.astype(float).tolist(),
           "state": "None", "source": "pairN", "type": "intersection"}
    first_rlp = rlps[group_indices[0]]
    first_rlp.setdefault("vectors", [])
    first_rlp["vectors"].append(dict(vec))


def augment_vectors_for_pairs_with_map(rlps: List[dict], min_count: int = 2) -> None:
    """Add pair-level suggestions only when an (i,j) pair has ≥ min_count RLPs."""
    print("[info] Augmenting vectors for pairs...")
    link_map = build_link_map(rlps)
    for _, idxs in link_map.items():
        if len(idxs) >= min_count:
            augment_for_group(rlps, idxs)
    print("[info] Vector augmentation finished.")


# =============================================================================
# Stage (entry point)
# =============================================================================
def stage_segment(cfgs):
    """
    1) Part selection (UI) → categories
    2) Separation → RLP clustering → vector candidates (+UI selection)
    3) Save per-link meshes from labels
    4) Patch fill (harmonic) and append to meshes
    5) Persist states (states.segment.*)
    """

    segCfgs = cfgs.params["segment"]

    print("=" * 60)
    print("[info] Starting stage_segment...")
    
    # load states & base mesh
    print("[info] Loading states and base mesh...")
    states = JsonHandler(cfgs.json_states_dir, auto_save=True)
    parts = [trimesh.load(states.decompose.dirs.mesh[i]) for i in range(states.decompose.length)]

    ms = pymeshlab.MeshSet()
    mesh_in_dir = states.refine.dirs.mesh
    ms.load_new_mesh(mesh_in_dir)
    ms.set_current_mesh(0)
    current_mesh = ms.current_mesh()
    verts = current_mesh.vertex_matrix()
    faces = current_mesh.face_matrix().astype(np.int64)

    categories_num = cfgs.categories_num
    
    # selection UI
    if cfgs.debug_mode:
        print("=" * 60)
        print("PART SELECTION STAGE CONTROLS:")
        print("  Mouse:")
        print("    Left Click  : Assign part to current selection mode")
        print("    Right Click : Revert assignment")
        print("  Keyboard:")
        print("    Tab         : Cycle selection mode (Category 1 -> 2 -> ... -> 0)")
        print("    Q / Esc     : Finish and Proceed")
        print("=" * 60)

    print("[info] Starting interactive part selection...")
    categories = select_parts(parts, verts, faces, categories_num)
    print("[info] Part selection finished.")
    
    # --- Compact categories by removing empty ones (keeping index 0) ---
    if len(categories) > 1:
        new_categories = [categories[0]]
        for c in categories[1:]:
            if c:
                new_categories.append(c)
        
        if len(new_categories) != len(categories):
            print(f"[info] Removed {len(categories) - len(new_categories)} empty categories.")
            categories = new_categories
            categories_num = len(categories) - 1
            print(f"[info] Updated categories_num: {categories_num}")
    # -------------------------------------------------------------------

    if not any(categories) and categories_num > 0:
        print("[warn] No parts selected.")

    # adjacency, vertex labels
    print("[info] Building adjacency graph and classifying vertices...")
    adj = adjacency(faces, len(verts))
    vert_label = label_vertices(verts, categories, **segCfgs["labeling"]).astype(int)
    print("[info] Graph build and classification finished.")

    if cfgs.debug_mode:
        show_labels(verts, faces, vert_label)

    # separation + clustering + vectors
    print("[info] Computing separation results...")
    results_list = compute_separation_results(
        verts, faces, categories_num, adj, vert_label,
        visualize_results=cfgs.debug_mode,
        **segCfgs["separator"]
    )

    print("[info] Clustering reciprocal loop pairs (RLPs)...")
    rlps = cluster_rlps(results_list, **segCfgs["rlp_clustering"])

    # Visualizing the RLP clustering details
    if cfgs.debug_mode:
        show_rlps(verts, faces, rlps)

    if segCfgs["allow_single_loop_rlp"]:
        append_single_loop_rlps(results_list, rlps, verts)

    print(f"[info]: len rlps {len(rlps)}")
    
    prepare_vectors_for_rlps(rlps)
    augment_vectors_for_pairs_with_map(rlps, min_count=segCfgs["vector_augment_min_count"])  # optional

    # vector selection UI (RLP-wise)
    if cfgs.debug_mode:
        print("=" * 60)
        print("VECTOR SELECTION STAGE CONTROLS (Per RLP Window):")
        print("  Mouse:")
        print("    Left Click on Vector : Toggle state (None -> Revolute -> Prismatic -> None)")
        print("  Keyboard (Applies to ALL vectors in current window):")
        print("    W / S     : Move along X axis")
        print("    D / A     : Move along Y axis")
        print("    Space / Z : Move along Z axis")
        print("    N / B     : Rotate around X axis")
        print("    H / J     : Rotate around Y axis")
        print("    U / I     : Rotate around Z axis")
        print("    Q / Esc   : Finish current window")
        print("=" * 60)

    print("[info] Starting interactive vector selection...")
    select_joint_vectors(rlps, verts, faces, vert_label)
    print("[info] Vector selection finished.")

    # save per-link meshes
    print("[info] Saving link meshes...")
    seg_dir = os.path.join(os.path.dirname(cfgs.json_states_dir), "segment_mesh")
    segment_mesh_paths = save_link_meshes(verts, faces, vert_label, categories_num, seg_dir)
    joints = joints_from_rlps(rlps)
    print("[info] Link meshes saved.")

    # persist states
    print("[info] Persisting states...")
    states.segment = {}
    states.segment.vert_label = vert_label.tolist()
    states.segment.dirs = {}
    states.segment.dirs.mesh = segment_mesh_paths
    states.segment.joints = joints
    print("[info] States persisted.")

    # patch fill & append
    print("[info] Building and appending patches...")
    patch_vertices, patch_faces = build_extrapoints_and_patches(results_list, verts)
    append_patches(segment_mesh_paths, patch_vertices, patch_faces)
    print("[info] Patches appended.")
    
    print("[info] stage_segment finished successfully.")
    print("=" * 60)
