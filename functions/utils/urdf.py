import os
import xml.etree.ElementTree as ET
from collections import defaultdict, deque

import numpy as np
import trimesh

from functions.math.geometry import normalize

URDF_TYPES = {"rev": "revolute", "pri": "prismatic", "pla": "planar", "sph": "floating"}
INERTIA_KEYS = {"ixx": (0, 0), "ixy": (0, 1), "ixz": (0, 2), "iyy": (1, 1), "iyz": (1, 2), "izz": (2, 2)}


def _xyz(v) -> str:
    v = np.asarray(v, dtype=float).ravel()
    return f"{v[0]:.9g} {v[1]:.9g} {v[2]:.9g}"


def _apply(T, p) -> np.ndarray:
    """Transform a point by 4x4 T (None = identity)."""
    p = np.asarray(p, dtype=float)
    if T is None:
        return p
    q = T @ np.append(p, 1.0)
    return q[:3] / q[3]


def urdf_transform(cfgs, states) -> np.ndarray | None:
    """Inverse of the alignment (aligned -> original frame) if requested and available, else None."""
    if not cfgs.urdf_use_original_coordinates:
        print("[info]: Generating outputs in ALIGNED coordinate system.")
        return None
    try:
        # states.transform.matrix maps original -> aligned; meshes/joints here are aligned, so invert it.
        if hasattr(states, "transform") and hasattr(states.transform, "matrix"):
            print("[info]: Generating outputs in ORIGINAL coordinate system (reverting alignment).")
            return np.linalg.inv(np.array(states.transform.matrix))
        print("[warn]: Transform matrix not found in states. Generating outputs in current (aligned) coordinates.")
    except Exception as e:
        print(f"[warn]: Failed to load/invert transform matrix: {e}. Generating outputs in current coordinates.")
    return None


# =============================================================================
# Joints
# =============================================================================
def suggestions_from_bicons(bicons: list[dict]) -> list[dict]:
    """Every vector candidate on the bicons, whatever its selection state:
    {"pair": (min, max), "origin", "n", "state"}."""
    out = []
    for bicon in bicons:
        p = int(bicon.get("a", {}).get("src", bicon.get("src", -1)))
        c = int(bicon.get("a", {}).get("dst", bicon.get("dst", -1)))
        if p < 0 or c < 0 or p == c:
            continue
        for v in bicon.get("vectors") or []:
            o = np.asarray(v.get("center", bicon.get("center", [0, 0, 0])), dtype=float).ravel()
            n = np.asarray(v.get("n") if v.get("n") is not None else v.get("n_poly"), dtype=float).ravel()
            if o.size != 3 or n.size != 3:
                continue
            n = normalize(n)
            if np.isfinite(o).all() and np.isfinite(n).all() and np.linalg.norm(n) >= 1e-12:
                out.append({"pair": (min(p, c), max(p, c)), "origin": o, "n": n, "state": v.get("state")})
    return out


def joints_from_bicons(bicons: list[dict]) -> list[dict]:
    """Joint candidates from the vectors selected on bicons (state Revolute/Prismatic).
    Vectors of one part pair sharing an origin merge: 2+ revolute -> Spherical, 2+ prismatic -> Planar.
    parent/child are (min, max) here; spanning_tree() decides the direction."""
    picked = [{**s, "type": s["state"]} for s in suggestions_from_bicons(bicons)
              if s["state"] in ("Revolute", "Prismatic")]
    if not picked:
        return []

    O = np.vstack([x["origin"] for x in picked])
    eps = max(float(np.linalg.norm(O.max(axis=0) - O.min(axis=0))) * 1e-4, 1e-8)

    by_pair = defaultdict(list)
    for it in picked:
        by_pair[it["pair"]].append(it)

    joints = []
    for pair, items in by_pair.items():
        # Greedy origin clustering (running mean center)
        groups, centers = [], []
        for it in items:
            gi = next((g for g, cen in enumerate(centers) if np.linalg.norm(it["origin"] - cen) <= eps), None)
            if gi is None:
                groups.append([it]); centers.append(it["origin"].copy())
            else:
                groups[gi].append(it)
                centers[gi] = centers[gi] + (it["origin"] - centers[gi]) / len(groups[gi])

        for group, origin in zip(groups, centers):
            jtype = group[0]["type"]  # mixed types: first wins
            dirs = np.vstack([it["n"] for it in group])
            n = dirs[0]
            if len(group) >= 2 and jtype == "Revolute":
                jtype = "Spherical"  # representative axis = first
            elif len(group) >= 2 and jtype == "Prismatic":
                jtype, n = "Planar", normalize(np.linalg.svd(dirs, full_matrices=False)[2][-1])
            joints.append({"parent": pair[0], "child": pair[1], "type": jtype,
                           "axis": {"origin": origin.astype(float).tolist(), "n": n.astype(float).tolist()}})
    return joints


def spanning_tree(raw_joints: list[dict], link_ids: list[int]):
    """BFS spanning tree from the smallest link id (smaller ids become parents; cycles dropped).
    Returns (tree joints with parent/child set, unreached link ids)."""
    if not link_ids:
        return [], set()
    adj = defaultdict(list)
    for j in raw_joints:
        p, c = int(j["parent"]), int(j["child"])
        adj[p].append((c, j)); adj[c].append((p, j))

    root = min(link_ids)
    visited, queue, tree = {root}, deque([root]), []
    while queue:
        u = queue.popleft()
        for v, j in sorted(adj[u], key=lambda x: x[0]):
            if v not in visited:
                visited.add(v)
                queue.append(v)
                tree.append({**j, "parent": u, "child": v})  # axis kept as is
    return tree, set(link_ids) - visited


# =============================================================================
# URDF
# =============================================================================
def mass_properties(mesh: trimesh.Trimesh, density: float):
    """(mass, center of mass, inertia tensor at the COM)."""
    m = mesh.copy()
    m.density = float(density)
    return float(m.mass), np.asarray(m.center_mass, dtype=float), np.asarray(m.moment_inertia, dtype=float)


def generate_urdf(closed_parts: dict[int, trimesh.Trimesh],
                  joints: list[dict],
                  *,
                  out_dir: str,
                  urdf_name: str = "robot",
                  density: float = 1000.0,
                  mesh_fmt: str = "stl",
                  base_origin=(0.0, 0.0, 0.0),
                  transform_matrix: np.ndarray = None,
                  suggestions: list[dict] = ()) -> str:
    """Write out_dir/<urdf_name>.urdf and out_dir/meshes/link_<id>.<mesh_fmt>.
    Meshes stay in world coords; each link frame sits at its joint origin.
    suggestions (from suggestions_from_bicons) become massless leaf links on link_<a>, one revolute joint
    suggest_<a>_<b>_<k> each at the candidate's origin/axis, so every candidate survives the tree."""
    T = transform_matrix
    meshes = {}
    os.makedirs(os.path.join(out_dir, "meshes"), exist_ok=True)
    for lid, mesh in closed_parts.items():
        meshes[lid] = mesh.copy()
        if T is not None:
            meshes[lid].apply_transform(T)
        meshes[lid].export(os.path.join(out_dir, "meshes", f"link_{lid}.{mesh_fmt}"))

    link_ids = sorted(closed_parts)
    tree, orphans = spanning_tree(joints, link_ids)

    # Link frame origins (world): child = joint origin, others = base origin
    base = _apply(T, base_origin)
    origin = {int(j["child"]): _apply(T, j["axis"]["origin"]) for j in tree}
    link_o = lambda lid: origin.get(lid, base)

    robot = ET.Element("robot", name=urdf_name)
    ET.SubElement(ET.SubElement(robot, "link", name="base"), "inertial").extend([
        ET.Element("origin", xyz="0 0 0", rpy="0 0 0"),
        ET.Element("mass", value="0.0"),
        ET.Element("inertia", ixx="0", ixy="0", ixz="0", iyy="0", iyz="0", izz="0"),
    ])

    for lid in link_ids:
        link = ET.SubElement(robot, "link", name=f"link_{lid}")
        mass, com, I = mass_properties(meshes[lid], density)
        for tag in ("visual", "collision"):
            el = ET.SubElement(link, tag)
            ET.SubElement(el, "origin", xyz=_xyz(np.zeros(3) - link_o(lid)), rpy="0 0 0")  # world mesh -> link frame (0 - x: no "-0")
            ET.SubElement(el, "geometry").append(ET.Element("mesh", filename=f"meshes/link_{lid}.{mesh_fmt}"))
        inertial = ET.SubElement(link, "inertial")
        ET.SubElement(inertial, "origin", xyz=_xyz(com - link_o(lid)), rpy="0 0 0")
        ET.SubElement(inertial, "mass", value=f"{mass:.9g}")
        ET.SubElement(inertial, "inertia", **{k: f"{I[ij]:.9g}" for k, ij in INERTIA_KEYS.items()})

    for j in tree:
        parent, child = int(j["parent"]), int(j["child"])
        urdf_type = URDF_TYPES.get(str(j.get("type") or "revolute").strip().lower()[:3], "revolute")
        j_el = ET.SubElement(robot, "joint", name=f"joint_{parent}_{child}", type=urdf_type)
        ET.SubElement(j_el, "parent", link=f"link_{parent}")
        ET.SubElement(j_el, "child", link=f"link_{child}")
        ET.SubElement(j_el, "origin", xyz=_xyz(link_o(child) - link_o(parent)), rpy="0 0 0")
        if urdf_type in ("revolute", "prismatic", "planar"):
            n = j["axis"].get("n") if isinstance(j.get("axis"), dict) else None
            axis = normalize(n if n is not None else [0, 0, 1])
            if T is not None:
                axis = normalize(T[:3, :3] @ axis)
            ET.SubElement(j_el, "axis", xyz=_xyz(axis))
        if urdf_type in ("revolute", "prismatic"):
            ET.SubElement(j_el, "limit", lower="-1.57", upper="1.57", effort="10.0", velocity="1.0")

    for k, s in enumerate(suggestions):
        a, b = s["pair"]
        name = f"suggest_{a}_{b}_{k}"
        ET.SubElement(robot, "link", name=f"{name}_axis")
        j_el = ET.SubElement(robot, "joint", name=name, type="revolute")  # suggestions carry no joint type
        ET.SubElement(j_el, "parent", link=f"link_{a}")
        ET.SubElement(j_el, "child", link=f"{name}_axis")
        ET.SubElement(j_el, "origin", xyz=_xyz(_apply(T, s["origin"]) - link_o(a)), rpy="0 0 0")
        ET.SubElement(j_el, "axis", xyz=_xyz(normalize(s["n"] if T is None else T[:3, :3] @ s["n"])))
        ET.SubElement(j_el, "limit", lower="-1.57", upper="1.57", effort="10.0", velocity="1.0")

    # Fix the tree root and every unreached link to base
    if link_ids:
        root = min(link_ids)
        for lid in [root] + sorted(orphans - {root}):
            name = f"base_to_{lid}" if lid == root else f"fixed_base_{lid}"
            fixed = ET.SubElement(robot, "joint", name=name, type="fixed")
            ET.SubElement(fixed, "parent", link="base")
            ET.SubElement(fixed, "child", link=f"link_{lid}")
            ET.SubElement(fixed, "origin", xyz=_xyz(link_o(lid)), rpy="0 0 0")

    tree_xml = ET.ElementTree(robot)
    ET.indent(tree_xml, space="  ")
    urdf_path = os.path.join(out_dir, f"{urdf_name}.urdf")
    tree_xml.write(urdf_path, encoding="utf-8", xml_declaration=True)
    return urdf_path
