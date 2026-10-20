import os
import trimesh
from typing import Dict, List, Tuple
from collections import defaultdict

import numpy as np
import pymeshlab

from json_handler import JsonHandler
from functions.math.geometry import normalize
from functions.math.graph import adjacency
from functions.math.patch import cycle_patch
from functions.math.connection import fuse_connections, unicon_normal, merge_lines, plane_intersections
from functions.math.axis_estimation import estimate_unicons
from functions.utils.mesh import append_patches, save_link_meshes
from functions.utils.urdf import generate_urdf, joints_from_bicons
from functions.gui.bridge import ui
from functions.visualize.plots import show_bicons, show_links


# =============================================================================
# Joint suggestion helpers (axis estimation, vectors, patches)
# =============================================================================
def compute_unicons(verts, faces, parts_num: int, adj, vert_label,
                    visualize_results: bool = False, **axis_kwargs) -> List[dict]:
    """Run estimate_unicons per part and flatten outputs."""
    print(f"[info] Starting axis estimation for {parts_num} parts...")
    unicons = []
    for idx_part in range(1, parts_num + 1):
        print(f"[info] Processing part {idx_part}/{parts_num}...")
        unicons += estimate_unicons(verts, faces, idx_part, adj, vert_label,
                                    visualize_results=visualize_results, **axis_kwargs)
    print(f"[info] Axis estimation finished. Total unicons: {len(unicons)}")
    return unicons


def prepare_vectors_for_bicons(bicons: List[dict]) -> None:
    """Create vector candidates on each bicon from plane/normal info."""
    print(f"[info] Preparing vectors for {len(bicons)} bicons...")
    for bicon in bicons:
        center = bicon['center']
        # Use the bicon normal computed in fuse_connections directly
        n_plane = np.asarray(bicon["normal"], dtype=float)

        A = bicon['a']['single_plane']; B = bicon['b']['single_plane']
        dA = float(A['plane'][0][1]) if A.get('plane') and len(A['plane']) > 0 else 0.0
        dB = float(B['plane'][0][1]) if B.get('plane') and len(B['plane']) > 0 else 0.0
        d_plane = 0.5 * (dA + dB)

        # 1. Add the main single-plane normal vector candidate (as list)
        bicon['vectors'] = [{
            'center': center if isinstance(center, list) else center.tolist(),
            'n': n_plane.tolist(),
            'd': d_plane.tolist() if isinstance(d_plane, np.ndarray) else d_plane,
            'type': 'normal'
        }]

        # 2-3. Multi-plane intersection lines from BOTH directions, matched and merged
        merged_lines = merge_lines(plane_intersections(bicon['a'].get('multi_plane', {}).get('plane') or []),
                                   plane_intersections(bicon['b'].get('multi_plane', {}).get('plane') or []))

        # 4. Add the first merged intersection line & the 3rd recommended vector
        if len(merged_lines) > 0:
            line = merged_lines[0]
            # Add intersection line candidate
            bicon['vectors'].append({
                'center': center if isinstance(center, list) else center.tolist(),
                'n': line.tolist(),
                'd': [0.0, 0.0, 0.0],
                'type': 'intersection'
            })

            # Add 3rd vector (perpendicular to both main plane normal and the intersection line)
            n_third = np.cross(n_plane, line)
            if np.linalg.norm(n_third) > 1e-6:
                bicon['vectors'].append({
                    'center': center if isinstance(center, list) else center.tolist(),
                    'n': normalize(n_third).tolist(),
                    'd': [0.0, 0.0, 0.0],
                    'type': 'cross'
                })

    print("[info] Vector preparation finished.")


def build_extrapoints_and_patches(unicons: List[dict],
                                  verts: np.ndarray):
    """For each cycle: dense sampling + triangulated patch."""
    print("[info] Building extra points and patches...")
    patch_vertices: Dict[int, List[np.ndarray]] = defaultdict(list)
    patch_faces: Dict[int, List[np.ndarray]] = defaultdict(list)
    for unicon in unicons:
        pid = int(unicon.get('src', 0))
        cycle_idx = unicon.get('cycle', None)
        if pid <= 0 or cycle_idx is None or len(cycle_idx) < 3:
            continue
        cycle_xyz = verts[np.asarray(cycle_idx, dtype=int)]
        P3, F = cycle_patch(cycle_xyz, step_rel=0.03, sigma_scale=2.0, k_min=6)
        if P3.size and F.size:
            patch_vertices[pid].append(P3.astype(float))
            patch_faces[pid].append(F.astype(np.int64))
    print("[info] Patch building finished.")
    return patch_vertices, patch_faces


def append_unpaired_unicons(unicons: List[dict], bicons: List[dict], verts: np.ndarray) -> None:
    """Find (i, j) part pairs that have 1 unicon on one side and 0 on the other, and add them as bicons."""
    print("[info] Checking for unpaired unicons (1-0 cases)...")
    pair_to_unicons = defaultdict(list)
    for unicon in unicons:
        s = unicon.get('src', -1)
        d = unicon.get('dst', -1)
        if s != -1 and d != -1:
            pair_to_unicons[(s, d)].append(unicon)

    checked = set()
    count = 0
    for (s, d) in pair_to_unicons.keys():
        key = tuple(sorted([s, d]))
        if key in checked: continue
        checked.add(key)

        p1, p2 = key
        unicons_12 = pair_to_unicons.get((p1, p2), [])
        unicons_21 = pair_to_unicons.get((p2, p1), [])

        # Exactly one unicon in one direction (1,0) or (0,1)
        if (len(unicons_12) == 1 and len(unicons_21) == 0) or (len(unicons_12) == 0 and len(unicons_21) == 1):
            single = unicons_12[0] if len(unicons_12) == 1 else unicons_21[0]

            already_in = False
            for b in bicons:
                if b.get('a') is single or b.get('b') is single:
                    already_in = True
                    break

            if not already_in:
                cycle_idx = single.get('cycle', [])
                if len(cycle_idx) > 0:
                    center = np.mean(verts[np.asarray(cycle_idx, dtype=int)], axis=0)
                else:
                    center = np.zeros(3)

                n_val = unicon_normal(single)
                bicon = {
                    'parts': key,
                    'a': single,
                    'b': single,  # duplicate into b so downstream code doesn't break
                    'center': center.tolist(),
                    'normal': n_val.tolist(),
                    'cost': 0.0,
                    'src': single.get('src', -1),
                    'dst': single.get('dst', -1),
                    'is_unpaired': True
                }
                bicons.append(bicon)
                count += 1

    if count > 0:
        print(f"[info] Appended {count} unpaired unicon(s) as bicons.")


# =============================================================================
# Link-pair utilities (used for augmentation only)
# =============================================================================
def build_link_map(bicons: List[dict]) -> Dict[Tuple[int, int], List[int]]:
    """(i,j)(i<j) -> indices of bicons connecting the two parts."""
    link_map: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for idx, b in enumerate(bicons):
        s = int(b.get("a", {}).get("src", b.get("src", -1)))
        d = int(b.get("a", {}).get("dst", b.get("dst", -1)))
        if s < 0 or d < 0 or s == d:
            continue
        key = (s, d) if s < d else (d, s)
        link_map[key].append(idx)
    return link_map


def pick_normal_from_bicon(bicon: dict) -> np.ndarray | None:
    """Try bicon normal first, then fallback to single-plane/PCA normal."""
    if "normal" in bicon:
        n = np.asarray(bicon["normal"], dtype=float)
        if np.isfinite(n).all() and np.linalg.norm(n) > 1e-12:
            return normalize(n)

    plane = bicon.get("single_plane", {}).get("plane", None)
    if plane and len(plane) >= 1 and len(plane[0]) >= 1:
        n = np.asarray(plane[0][0], dtype=float)
        if np.isfinite(n).all() and np.linalg.norm(n) > 1e-12:
            return normalize(n)
    n = np.asarray(bicon.get("pca_normal", None), dtype=float) if bicon.get("pca_normal", None) is not None else None
    if n is None or not np.isfinite(n).all() or np.linalg.norm(n) < 1e-12:
        return None
    return normalize(n)


def augment_for_group(bicons: List[dict], group_indices: List[int]) -> None:
    """Add a pair-level vector suggestion into each bicon in the group."""
    if len(group_indices) < 2:
        return
    centers, normals, weights = [], [], []
    for i in group_indices:
        b = bicons[i]
        ctr = np.asarray(b.get("center", None), dtype=float)
        nrm = pick_normal_from_bicon(b)
        if ctr is None or ctr.size != 3 or not np.isfinite(ctr).all():
            continue
        centers.append(ctr); normals.append(nrm)
        cycle_idx = b.get("cycle", [])
        w = int(len(cycle_idx)) if cycle_idx is not None else 1
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
        first_bicon = bicons[group_indices[0]]
        first_bicon.setdefault("vectors", [])
        first_bicon["vectors"].append(dict(vec))
        return

    # 3 or more bicons
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
    first_bicon = bicons[group_indices[0]]
    first_bicon.setdefault("vectors", [])
    first_bicon["vectors"].append(dict(vec))


def augment_vectors_for_pairs_with_map(bicons: List[dict], min_count: int = 2) -> None:
    """Add pair-level suggestions only when an (i,j) pair has ≥ min_count bicons."""
    print("[info] Augmenting vectors for pairs...")
    link_map = build_link_map(bicons)
    for _, idxs in link_map.items():
        if len(idxs) >= min_count:
            augment_for_group(bicons, idxs)
    print("[info] Vector augmentation finished.")


# =============================================================================
# URDF
# =============================================================================
def urdf_transform(cfgs, states) -> np.ndarray | None:
    """Inverse of the alignment (aligned -> original frame) if requested and available, else None."""
    if not cfgs.urdf_use_original_coordinates:
        print("[info]: Generating URDF in ALIGNED coordinate system.")
        return None
    try:
        # states.transform.matrix maps original -> aligned; meshes/joints here are aligned, so invert it.
        if hasattr(states, "transform") and hasattr(states.transform, "matrix"):
            print("[info]: Generating URDF in ORIGINAL coordinate system (reverting alignment).")
            return np.linalg.inv(np.array(states.transform.matrix))
        print("[warn]: Transform matrix not found in states. Generating URDF in current (aligned) coordinates.")
    except Exception as e:
        print(f"[warn]: Failed to load/invert transform matrix: {e}. Generating URDF in current coordinates.")
    return None


# =============================================================================
# Stage (entry point)
# =============================================================================
def stage_articulate(cfgs):
    """
    1) Load refined mesh + vertex labels (segment stage output)
    2) Automatic Joint Suggestion: axis estimation (unicons) → bidirectional fusion (bicons) → vector candidates
    3) Joint selection (UI)
    4) Link meshes + patch fill, URDF generation
    5) Persist states (states.articulate.*)
    """
    artCfgs = cfgs.params["articulate"]

    print("=" * 60)
    print("[info] Starting stage_articulate...")
    ui().plan([("load", "Load", True), ("unicons", "Unicons", True), ("fusion", "Fusion", True),
               ("vectors", "Vector selection", True), ("links", "Link meshes", True), ("urdf", "URDF", True)])
    ui().step("load")

    # load states, refined mesh & vertex labels
    print("[info] Loading states, base mesh and vertex labels...")
    states = JsonHandler(cfgs.json_states_dir, auto_save=True)

    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(states.refine.dirs.mesh)
    ms.set_current_mesh(0)
    current_mesh = ms.current_mesh()
    verts = current_mesh.vertex_matrix()
    faces = current_mesh.face_matrix().astype(np.int64)

    vert_label = np.load(states.segment.dirs.vert_label).astype(int)
    parts_num = int(states.segment.parts_num)
    if len(vert_label) != len(verts):
        raise RuntimeError(f"[error]: vert_label ({len(vert_label)}) does not match refined mesh ({len(verts)} verts). "
                           "Re-run the segment stage.")
    adj = adjacency(faces, len(verts))

    # axis estimation + fusion + vectors
    ui().step("unicons")
    print("[info] Estimating unidirectional connections (unicons)...")
    unicons = compute_unicons(
        verts, faces, parts_num, adj, vert_label,
        visualize_results=cfgs.debug_mode,
        **artCfgs["axis_estimation"]
    )

    ui().step("fusion")
    print("[info] Fusing unicons into bidirectional connections (bicons)...")
    bicons = fuse_connections(unicons, **artCfgs["fusion"])

    # Visualizing the fusion details
    if cfgs.debug_mode:
        show_bicons(verts, faces, bicons)

    if artCfgs["allow_unpaired_unicon"]:
        append_unpaired_unicons(unicons, bicons, verts)

    print(f"[info]: len bicons {len(bicons)}")

    prepare_vectors_for_bicons(bicons)
    augment_vectors_for_pairs_with_map(bicons, min_count=artCfgs["vector_augment_min_count"])  # optional

    # vector selection in the viewport (all part pairs in one scene)
    ui().step("vectors")
    print("[info] Starting interactive vector selection...")
    if bicons:
        from functions.gui.scenes import JointSelectScene  # GUI-only import
        ui().interact(JointSelectScene(bicons, verts, faces, vert_label))
    print("[info] Vector selection finished.")
    joints = joints_from_bicons(bicons)

    # per-link meshes + patch fill
    ui().step("links")
    print("[info] Saving link meshes...")
    link_dir = os.path.join(cfgs.mesh_working_dir, "links")
    link_mesh_paths = save_link_meshes(verts, faces, vert_label, parts_num, link_dir)
    patch_vertices, patch_faces = build_extrapoints_and_patches(unicons, verts)
    append_patches(link_mesh_paths, patch_vertices, patch_faces)
    print("[info] Link meshes saved.")

    # persist states
    print("[info] Persisting states...")
    states.articulate = {}
    states.articulate.dirs = {}
    states.articulate.dirs.mesh = link_mesh_paths
    states.articulate.joints = joints
    print("[info] States persisted.")

    links: Dict[int, trimesh.Trimesh] = {int(k): trimesh.load(p, process=False) for k, p in link_mesh_paths.items()}
    if not links:
        print("[error]: No link meshes were generated.")
        return

    ui().step("urdf")
    # Generate URDF File (urdf_name / density / mesh_fmt from parameters_cfg.yml)
    urdf_dir = generate_urdf(
        closed_parts=links,
        joints=joints,
        out_dir=cfgs.urdf_out_dir,
        transform_matrix=urdf_transform(cfgs, states),
        **artCfgs["urdf"]
    )
    print(f"[info]: the urdf file has been generated in: {urdf_dir}")

    # Debug checkpoint: the articulated object's link meshes
    show_links(links)

    print("[info] stage_articulate finished successfully.")
    print("=" * 60)
