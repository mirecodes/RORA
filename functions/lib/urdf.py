import os
import numpy as np
import trimesh
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Set
from collections import defaultdict, deque
from functions.lib.geometry import normalize


# ================================
# Small math / format helpers
# ================================
def to_str_xyz(v):
    v = np.asarray(v, dtype=float).ravel()
    return f"{v[0]:.9g} {v[1]:.9g} {v[2]:.9g}"


def mapping_get(mapping, key):
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except Exception:
        try:
            return mapping[key]
        except Exception:
            return None


# =============================================================================
# Joint building
# =============================================================================
def build_joints_from_rlps(rlps: List[dict]) -> List[dict]:
    """
    Extract joint candidates from RLPs (Radial Line Pairs).
    No tree structure enforced yet; returns every geometric connection found.
    """
    picked = []
    for rlp in rlps:
        p = int(rlp.get("a", {}).get("parent", rlp.get("parent", -1)))
        c = int(rlp.get("a", {}).get("child", rlp.get("child", -1)))

        # Validate
        if p < 0 or c < 0 or p == c:
            continue

        # Sort to an (i < j) pair key; direction is fixed later in tree building
        i, j = (p, c) if p < c else (c, p)

        for v in (rlp.get("vectors") or []):
            st = v.get("state")
            if st not in ("Revolute", "Prismatic"):
                continue
            o = np.asarray(v.get("center", rlp.get("center", [0, 0, 0])), dtype=float).ravel()
            n = np.asarray(v.get("n") if v.get("n") is not None else v.get("n_poly"), dtype=float).ravel()

            if o.size != 3 or n.size != 3: continue
            n = normalize(n)
            if not np.isfinite(o).all() or not np.isfinite(n).all() or np.linalg.norm(n) < 1e-12:
                continue

            picked.append({"pair": (i, j), "origin": o, "n": n, "type": st})

    if not picked:
        return []

    # Cluster vectors sharing the same origin
    O = np.vstack([x["origin"] for x in picked])
    bb = O.max(axis=0) - O.min(axis=0)
    diag = float(np.linalg.norm(bb))
    eps = max(diag * 1e-4, 1e-8)

    def _cluster_origins(items):
        groups = []
        centers = []
        for k, it in enumerate(items):
            o = it["origin"]
            assigned = False
            for gi, cen in enumerate(centers):
                if np.linalg.norm(o - cen) <= eps:
                    groups[gi].append(k)
                    centers[gi] = centers[gi] + (o - centers[gi]) / float(len(groups[gi]))
                    assigned = True
                    break
            if not assigned:
                groups.append([k])
                centers.append(o.copy())
        return groups, np.vstack(centers) if centers else np.zeros((0, 3))

    by_pair: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for idx, it in enumerate(picked):
        by_pair[it["pair"]].append(idx)

    joints = []
    for pair, idxs in by_pair.items():
        sub = [picked[k] for k in idxs]
        groups, group_centers = _cluster_origins(sub)

        for g_idx, g in enumerate(groups):
            items = [sub[k] for k in g]
            origin = group_centers[g_idx]
            types = {it["type"] for it in items}

            # Mixed types: take the first
            jtype = next(iter(types))
            dirs = np.vstack([it["n"] for it in items])

            # parent/child stored as (min, max) for now;
            # build_valid_tree_joints decides direction
            joint_def = {
                "parent": pair[0], "child": pair[1],
                "axis": {"origin": origin.astype(float).tolist()},
                "type": jtype
            }

            if jtype == "Revolute" and len(items) >= 2:
                # Multi-axis revolute -> Spherical
                joint_def["type"] = "Spherical"
                joint_def["axis"]["n"] = dirs[0].astype(float).tolist()  # representative axis
            elif jtype == "Prismatic" and len(items) >= 2:
                # Multi-axis prismatic -> Planar
                _, _, Vt = np.linalg.svd(dirs, full_matrices=False)
                n_plane = normalize(Vt[-1])
                joint_def["type"] = "Planar"
                joint_def["axis"]["n"] = n_plane.astype(float).tolist()
            else:
                # Single-axis joint
                n = dirs[0]
                joint_def["axis"]["n"] = n.astype(float).tolist()

            joints.append(joint_def)

    return joints


# ================================
# Tree Logic (New Algorithm)
# ================================
def build_valid_tree_joints(raw_joints: List[dict], all_link_ids: List[int]) -> Tuple[List[dict], Set[int]]:
    """
    Build a joint graph and extract an acyclic spanning tree via BFS.
    1. Smaller IDs are preferred as parents.
    2. Breaks cycles and reports disconnected nodes.
    """
    if not all_link_ids:
        return [], set()

    # 1. Undirected adjacency list
    # adj[u] = [(v, joint_info), ...]
    adj = defaultdict(list)
    for j in raw_joints:
        p, c = int(j["parent"]), int(j["child"])
        # Keep original joint data
        adj[p].append((c, j))
        adj[c].append((p, j))

    # 2. BFS init
    # Root = smallest ID (usually 1)
    root_id = min(all_link_ids)
    visited = {root_id}
    queue = deque([root_id])

    valid_joints = []

    # 3. BFS
    while queue:
        u = queue.popleft()

        # Visit neighbors in ID order so smaller IDs tend to be parents
        neighbors = sorted(adj[u], key=lambda x: x[0])

        for v, j_info in neighbors:
            if v in visited:
                continue

            # First visit of v -> u is parent, v is child
            visited.add(v)
            queue.append(v)

            # Copy joint and reset parent/child
            new_joint = j_info.copy()
            new_joint["parent"] = u
            new_joint["child"] = v

            # If parent/child got swapped vs. the original, the axis is kept as is
            # (the axis line itself is unchanged; physical meaning is up to the user).

            valid_joints.append(new_joint)

    # 4. Isolated nodes (not visited)
    unvisited = set(all_link_ids) - visited

    return valid_joints, unvisited


# ================================
# URDF Generation
# ================================
def export_meshes(meshes: Dict[int, trimesh.Trimesh], out_dir: str, fmt: str = "stl") -> Dict[int, str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for lid, mesh in meshes.items():
        path = os.path.join(out_dir, f"link_{lid}.{fmt}")
        mesh.export(path)
        paths[lid] = path
    return paths


def compute_mass_inertia_at_com(mesh: trimesh.Trimesh, density: float):
    com = np.asarray(mesh.center_mass, dtype=float)
    try:
        vol = float(mesh.volume)
    except Exception:
        vol = 0.0
    mass = float(density) * vol

    # I at COM
    T = np.eye(4);
    T[:3, 3] = -com
    moved = mesh.copy()
    try:
        moved.apply_transform(T)
    except Exception:
        pass

    I_attr = getattr(moved, "moment_inertia", None)
    if callable(I_attr):
        try:
            I_com = I_attr(density=density)
        except TypeError:
            I_com = I_attr(mass=mass)
    elif isinstance(I_attr, np.ndarray):
        I_com = np.asarray(I_attr, dtype=float) * float(density)
    else:
        mp = getattr(moved, "mass_properties", None)
        I_com = np.asarray(mp["inertia"], dtype=float) if isinstance(mp, dict) and "inertia" in mp else np.zeros((3, 3),
                                                                                                                 float)
    return mass, com, I_com


def urdf_inertia_dict(I):
    return {
        "ixx": float(I[0, 0]), "ixy": float(I[0, 1]), "ixz": float(I[0, 2]),
        "iyy": float(I[1, 1]), "iyz": float(I[1, 2]), "izz": float(I[2, 2]),
    }


def gather_link_frame_origins(joints, base_origin=np.zeros(3), transform_matrix=None):
    """
    Compute each link's world origin from tree-ordered joints.
    """
    base_origin = np.asarray(base_origin, float)
    if transform_matrix is not None:
        p_h = np.append(base_origin, 1.0)
        p_trans = np.dot(transform_matrix, p_h)
        base_origin = p_trans[:3] / p_trans[3]

    link_o = {0: base_origin}  # 0 reserved for base

    # joints are BFS-ordered (parents first), but use dicts to be safe

    # 1. Tree lookups
    children_of = defaultdict(list)
    joint_by_child = {}
    for j in joints:
        p, c = int(j["parent"]), int(j["child"])
        children_of[p].append(c)
        joint_by_child[c] = j

    # 2. Roots (top-level parents never appearing as child)
    # Usually link_1, depending on build_valid_tree_joints
    # The caller attaches link_1 to base

    # Collect all link IDs
    all_links = set()
    for j in joints:
        all_links.add(int(j["parent"]))
        all_links.add(int(j["child"]))

    # Recursive position calc
    def _calc_pos(lid, parent_pos):
        link_o[lid] = parent_pos  # relative to parent for now...
        # Note: in URDF, link origin usually matches the visual mesh origin (world);
        # the joint origin becomes the link's pivot.

        # Stores where each link sits in world (mesh origin basis);
        # once the parent is known, the child joint origin follows.
        pass

    # Joint 'origin' is already in world coords (input data), independent of
    # parent/child, so just iterate joints and store it.

    for j in joints:
        c = int(j["child"])
        o = np.asarray(j["axis"]["origin"], dtype=float)

        if transform_matrix is not None:
            p_h = np.append(o, 1.0)
            p_trans = np.dot(transform_matrix, p_h)
            o = p_trans[:3] / p_trans[3]

        link_o[c] = o  # child link pivot (joint origin)

        # Parent not yet in link_o (top-level root):
        # use base origin, since link_1 is attached to base via base_joint
        p = int(j["parent"])
        if p not in link_o:
            link_o[p] = base_origin

    return link_o


def generate_urdf(
        closed_parts: Dict[int, trimesh.Trimesh],
        joints: List[dict],
        *,
        out_dir: str,
        urdf_name: str = "robot",
        density: float = 1000.0,
        mesh_fmt: str = "stl",
        base_origin=(0.0, 0.0, 0.0),
        transform_matrix: np.ndarray = None,
):
    os.makedirs(out_dir, exist_ok=True)
    
    # [Fix] Apply transform to meshes if needed before exporting
    if transform_matrix is not None:
        print("[Info] Applying transform to meshes for URDF export...")
        meshes_to_export = {}
        for lid, mesh in closed_parts.items():
            m = mesh.copy()
            m.apply_transform(transform_matrix)
            meshes_to_export[lid] = m
    else:
        meshes_to_export = closed_parts
        
    mesh_paths = export_meshes(meshes_to_export, os.path.join(out_dir, "meshes"), fmt=mesh_fmt)

    # ==========================================
    # 1. Rebuild tree (Tree Logic Applied Here)
    # ==========================================
    link_ids = sorted(closed_parts.keys())

    # BFS removes cycles; prefers parent < child.
    tree_joints, unvisited_links = build_valid_tree_joints(joints, link_ids)

    # ==========================================
    # 2. Link origins
    # ==========================================
    link_frame_origin = gather_link_frame_origins(tree_joints, base_origin, transform_matrix)

    # Isolated (unvisited) links default to base_origin
    for uid in unvisited_links:
        if uid not in link_frame_origin:
            # Apply transform
            bo = np.asarray(base_origin, float)
            if transform_matrix is not None:
                bo = (np.dot(transform_matrix, np.append(bo, 1.0)))[:3]
            link_frame_origin[uid] = bo

    # ==========================================
    # 3. Build XML
    # ==========================================
    robot = ET.Element("robot", name=urdf_name)

    # Base Link
    base_link = ET.SubElement(robot, "link", name="base")
    ET.SubElement(base_link, "inertial").extend([
        ET.Element("origin", xyz="0 0 0", rpy="0 0 0"),
        ET.Element("mass", value="0.0"),
        ET.Element("inertia", ixx="0", ixy="0", ixz="0", iyy="0", iyz="0", izz="0")
    ])

    # Regular Links
    for lid in link_ids:
        link = ET.SubElement(robot, "link", name=f"link_{lid}")
        
        # Use the transformed mesh for mass calculation as well
        mesh_for_calc = meshes_to_export[lid]
        mass, com_world, I_com = compute_mass_inertia_at_com(mesh_for_calc, density=density)

        link_o_world = link_frame_origin.get(lid, np.zeros(3))

        # Visual/Collision Origin = - (Link Frame Origin)
        # Mesh files are in world coords, so offset the visual origin
        # inversely to align the mesh with the link frame
        rel_xyz = to_str_xyz(np.asarray([0, 0, 0], float) - link_o_world)

        # Visual
        visual = ET.SubElement(link, "visual")
        ET.SubElement(visual, "origin", xyz=rel_xyz, rpy="0 0 0")
        ET.SubElement(visual, "geometry").append(
            ET.Element("mesh", filename=os.path.relpath(mesh_paths[lid], out_dir))
        )

        # Collision
        collision = ET.SubElement(link, "collision")
        ET.SubElement(collision, "origin", xyz=rel_xyz, rpy="0 0 0")
        ET.SubElement(collision, "geometry").append(
            ET.Element("mesh", filename=os.path.relpath(mesh_paths[lid], out_dir))
        )

        # Inertial (COM relative to Link Frame)
        com_in_link = com_world - link_o_world
        inertial = ET.SubElement(link, "inertial")
        ET.SubElement(inertial, "origin", xyz=to_str_xyz(com_in_link), rpy="0 0 0")
        ET.SubElement(inertial, "mass", value=f"{mass:.9g}")
        I = urdf_inertia_dict(I_com)
        ET.SubElement(inertial, "inertia", **{k: f"{v:.9g}" for k, v in I.items()})

    # Joints (from Tree)
    for j in tree_joints:
        parent, child = int(j["parent"]), int(j["child"])
        parent_name = f"link_{parent}"  # tree joints always connect link_X to link_X
        child_name = f"link_{child}"

        # Origin Calc
        joint_world_o = np.asarray(j["axis"]["origin"], dtype=float)
        if transform_matrix is not None:
            p_h = np.append(joint_world_o, 1.0)
            p_trans = np.dot(transform_matrix, p_h)
            joint_world_o = p_trans[:3] / p_trans[3]

        parent_world_o = link_frame_origin.get(parent, np.zeros(3))
        joint_in_parent = joint_world_o - parent_world_o

        # Type Parsing
        jtype_raw = str(mapping_get(j, "type") or "revolute").strip().lower()
        if jtype_raw.startswith("rev"):
            urdf_type = "revolute"
        elif jtype_raw.startswith("pri"):
            urdf_type = "prismatic"
        elif jtype_raw.startswith("pla"):
            urdf_type = "planar"
        elif jtype_raw.startswith("sph"):
            urdf_type = "floating"
        else:
            urdf_type = "revolute"

        j_el = ET.SubElement(robot, "joint", name=f"joint_{parent}_{child}", type=urdf_type)
        ET.SubElement(j_el, "parent", link=parent_name)
        ET.SubElement(j_el, "child", link=child_name)
        ET.SubElement(j_el, "origin", xyz=to_str_xyz(joint_in_parent), rpy="0 0 0")

        if urdf_type in ("revolute", "prismatic", "planar"):
            n_raw = mapping_get(j, "axis")
            n_vec = mapping_get(n_raw, "n") if isinstance(n_raw, dict) else None
            axis = normalize(n_vec if n_vec is not None else [0, 0, 1])
            if transform_matrix is not None:
                axis = normalize(np.dot(transform_matrix[:3, :3], axis))
            ET.SubElement(j_el, "axis", xyz=to_str_xyz(axis))

        if urdf_type in ("revolute", "prismatic"):
            ET.SubElement(j_el, "limit", lower="-1.57", upper="1.57", effort="10.0", velocity="1.0")

    # ==========================================
    # 4. Base & Disconnected Link Handling
    # ==========================================
    # 4-1. Main Root Connection (Base -> Link 1 or min_id)
    # Fix the tree root (BFS start) to base
    if link_ids:
        root_id = min(link_ids)  # BFS start ID
        base_joint = ET.SubElement(robot, "joint", name=f"base_to_{root_id}", type="fixed")
        ET.SubElement(base_joint, "parent", link="base")
        ET.SubElement(base_joint, "child", link=f"link_{root_id}")

        root_origin = link_frame_origin.get(root_id, np.zeros(3))
        ET.SubElement(base_joint, "origin", xyz=to_str_xyz(root_origin), rpy="0 0 0")

    # 4-2. Floating Nodes Connection (Base -> Orphan)
    # Fix links with no joint (missing from tree) to base
    for uid in unvisited_links:
        if uid == min(link_ids): continue  # already attached above

        fix_joint = ET.SubElement(robot, "joint", name=f"fixed_base_{uid}", type="fixed")
        ET.SubElement(fix_joint, "parent", link="base")
        ET.SubElement(fix_joint, "child", link=f"link_{uid}")

        # Isolated link origin = base origin (or 0,0,0)
        u_origin = link_frame_origin.get(uid, np.zeros(3))
        ET.SubElement(fix_joint, "origin", xyz=to_str_xyz(u_origin), rpy="0 0 0")

    # Save
    tree = ET.ElementTree(robot)
    urdf_path = os.path.join(out_dir, f"{urdf_name}.urdf")
    ET.indent(tree, space="  ")
    tree.write(urdf_path, encoding="utf-8", xml_declaration=True)
    return urdf_path