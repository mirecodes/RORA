from dataclasses import dataclass
from typing import Dict, Optional
import os
import numpy as np
from plyfile import PlyData

from functions.render.urdf_parser import URDFParser  # ← separate file
from functions.stages.transform import _closest_rotation, save_gaussian_with_transform



# ---- Reuse existing helpers as-is ----
# from your_module import _closest_rotation, save_gaussian_with_transform
# Assumed to be in the same file here
# _closest_rotation(M4), save_gaussian_with_transform(ply: PlyData, out_path: str, T4: np.ndarray)

@dataclass
class RenderConfig:
    urdf_path: str
    mesh_root: str
    gauss_root: str
    link_to_gauss: Dict[str, str]
    q: Dict[str, float]
    out_dir: Optional[str] = None
    gaussian_out_name: Optional[str] = None
    use_visual_origin: bool = True
    chain_all_joints: bool = True
    clamp_joint_limits: bool = False   # ← default: respect URDF limits
    debug: bool = True



def _print_T(name: str, T: np.ndarray):
    # Print matrix + R/t split
    R = T[:3, :3]
    t = T[:3, 3]
    print(f"[T] link={name}")
    print(np.array2string(T, formatter={'float_kind':lambda x: f"{x: .6f}"}))
    print(f"    t = ({t[0]:.6f}, {t[1]:.6f}, {t[2]:.6f})")
    # Determinant/orthogonality check
    detR = np.linalg.det(R)
    ortho_err = np.linalg.norm(R.T @ R - np.eye(3))
    print(f"    det(R)={detR:.6f}, ||R^T R - I||_F={ortho_err:.3e}")

def _print_T_full(tag: str, T: np.ndarray):
    R = T[:3, :3]
    t = T[:3, 3]
    def _axis_angle(Rm):
        # numerical safety
        val = (np.trace(Rm) - 1) / 2.0
        val = np.clip(val, -1.0, 1.0)
        theta = float(np.arccos(val))
        axis = np.array([Rm[2,1]-Rm[1,2], Rm[0,2]-Rm[2,0], Rm[1,0]-Rm[0,1]])
        n = np.linalg.norm(axis)
        if n < 1e-12:
            return np.array([1.0, 0.0, 0.0]), 0.0
        return axis / n, theta
    axis, ang = _axis_angle(R)
    print(f"[{tag}]")
    print(np.array2string(T, formatter={'float_kind': lambda x: f"{x: .6f}"}))
    print(f"    t=({t[0]:.6f}, {t[1]:.6f}, {t[2]:.6f}), detR={np.linalg.det(R):.6f}, angle(rad)={ang:.6f}, axis=({axis[0]:.6f},{axis[1]:.6f},{axis[2]:.6f})")

from plyfile import PlyData, PlyElement

def _collect_vertex_schema(ply_paths):
    """
    Collect vertex schemas (field name, dtype) of all PLYs into a
    field union and final dtype map.
    - Per-field dtype upcast via numpy.result_type
    - Scalar properties only (list properties skipped)
    Returns: (field_order, field_dtype_map)
      - field_order: final field order (list[str])
      - field_dtype_map: {field: np.dtype}
    """
    dtype_map = {}  # field -> dtype
    order = []      # first-seen order

    for p in ply_paths:
        ply = PlyData.read(p)
        v = ply['vertex']
        names = list(v.data.dtype.names or [])
        for name in names:
            dt = v.data.dtype.fields[name][0]
            if name not in dtype_map:
                dtype_map[name] = dt
                order.append(name)
            else:
                dtype_map[name] = np.result_type(dtype_map[name], dt)
    return order, dtype_map

def _vertex_to_unified_recarray(ply: PlyData, field_order, field_dtype_map):
    """
    Convert one PLY's vertices to a recarray matching the given schema
    (field_order, field_dtype_map). Missing fields are zero-filled.
    """
    v = ply['vertex']
    n = len(v.data)
    unified_dtype = [(name, field_dtype_map[name]) for name in field_order]
    out = np.zeros(n, dtype=unified_dtype)

    src_names = v.data.dtype.names or ()
    for name in field_order:
        if name in src_names:
            out[name] = v[name].astype(field_dtype_map[name], copy=False)
        else:
            # Missing field stays 0 (safe for float/uint)
            pass
    return out

def merge_gaussians_to_single_ply(ply_paths, out_path, *, text=None):
    """
    Merge multiple (already world-space) Gaussian PLYs into one.
    - Only scalar vertex properties merged (list properties/other elements ignored)
    - Unified to the field-union schema
    - Header text/binary mode follows the first file unless text=True/False is given
    """
    ply_paths = [p for p in ply_paths if p and os.path.isfile(p)]
    if not ply_paths:
        raise FileNotFoundError("No valid PLY paths to merge.")

    # 1) Build final schema
    field_order, field_dtype_map = _collect_vertex_schema(ply_paths)

    # 2) Convert each file to unified recarray, then concat
    chunks = []
    for p in ply_paths:
        ply = PlyData.read(p)
        arr = _vertex_to_unified_recarray(ply, field_order, field_dtype_map)
        chunks.append(arr)
    if not chunks:
        raise RuntimeError("No vertices found to merge.")

    merged = np.concatenate(chunks, axis=0)

    # 3) Build PlyElement and write
    vertex_el = PlyElement.describe(merged, 'vertex')

    # Header mode: first file's text/binary unless text is given
    first = PlyData.read(ply_paths[0])
    out_ply = PlyData([vertex_el], text=(first.text if text is None else bool(text)))
    out_ply.byte_order = first.byte_order  # match first file
    # Keep only the first file's metadata
    out_ply.comments = list(first.comments)
    out_ply.obj_info = list(first.obj_info)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out_ply.write(out_path)
    return out_path


def render_gaussians_with_fk(cfg: RenderConfig) -> Dict[str, str]:
    parser = URDFParser.from_file(cfg.urdf_path)
    link_T = parser.link_transforms(cfg.q)

    # ---- Debug: raw T of every link ----
    if cfg.debug:
        print("[DEBUG] q =", {k: float(v) for k, v in cfg.q.items()})
        print(f"[DEBUG] #links={len(parser.model.links)}, #joints={len(parser.model.joints)}, roots={parser.model.roots}")
        # Sorted by link name
        for link_name in sorted(link_T.keys()):
            _print_T(link_name, link_T[link_name])

        # Check if all T are identical (overlap diagnosis)
        Ts = list(link_T.values())
        if len(Ts) >= 2:
            same_all = all(np.allclose(Ts[0], Ti, atol=1e-8) for Ti in Ts[1:])
            if same_all:
                print("[WARN] All link transforms are identical. "
                      "Namespace/parent-child parsing may have failed, or all origins are (0,0,0).")

    out_dir = cfg.out_dir or os.path.join(cfg.gauss_root, "outputs")
    os.makedirs(out_dir, exist_ok=True)

    saved: Dict[str, str] = {}
    for link_name, ply_path in cfg.link_to_gauss.items():
        if not os.path.isfile(ply_path):
            print(f"[warn] missing gaussian for link '{link_name}': {ply_path}")
            continue
        if link_name not in link_T:
            print(f"[warn] no transform for link '{link_name}' (check URDF link names)")
            continue

        # Debug: compare T before/after orthonormalization
        T_raw = np.asarray(link_T[link_name], dtype=np.float64)
        T = _closest_rotation(T_raw)

        if cfg.debug:
            print(f"[DEBUG] apply transform to '{link_name}'")
            print("    (before _closest_rotation)")
            _print_T(f"{link_name} (raw)", T_raw)
            print("    (after _closest_rotation)")
            _print_T(f"{link_name} (closestR)", T)

        ply = PlyData.read(ply_path)
        out_path = os.path.join(out_dir, f"{link_name}_gaussian_world.ply")
        save_gaussian_with_transform(ply, out_path, T)
        saved[link_name] = out_path

    # --- Merge ---
    if saved:
        merged_out = os.path.join(out_dir, "gaussians_merged_world.ply")
        try:
            merge_gaussians_to_single_ply(list(saved.values()), merged_out)
            saved["_merged"] = merged_out
            if cfg.debug:
                print(f"[DEBUG] merged gaussian saved → {merged_out}")
        except Exception as e:
            print(f"[error] merge failed: {e}")

    return saved


def _print_T(tag: str, T: np.ndarray):
    R, t = T[:3,:3], T[:3,3]
    print(f"[{tag}] t=({t[0]:.6f},{t[1]:.6f},{t[2]:.6f}), detR={np.linalg.det(R):.6f}")

def render_gaussians_parent_to_child(cfg: RenderConfig) -> Dict[str, str]:
    parser = URDFParser.from_file(cfg.urdf_path)
    out_dir = cfg.out_dir or os.path.join(cfg.gauss_root, "outputs")
    os.makedirs(out_dir, exist_ok=True)

    saved: Dict[str, str] = {}

    for link_name, ply_path in cfg.link_to_gauss.items():
        if not os.path.isfile(ply_path):
            print(f"[warn] missing gaussian for link '{link_name}': {ply_path}")
            continue

        # 1) Compose joint chain: root → link, product of (origin ⨉ motion(q))
        if cfg.chain_all_joints:
            T_chain = parser.chain_T_to_link(link_name, cfg.q, clamp_limits=cfg.clamp_joint_limits)
            path = parser.joint_path_to(link_name)
        else:
            # Legacy: single parent→child step only
            parent = parser.parent_link_of(link_name)
            T_chain = np.eye(4) if parent is None else parser.relative_transform(parent, link_name, cfg.q)
            path = [parser.model.joints[parser.model.child_to_joint[link_name]]] if parent else []

        # 2) link → visual
        T_link_visual = parser.visual_T(link_name) if cfg.use_visual_origin else np.eye(4)

        # 3) Final: (joint chain) · (visual)
        T_total = _closest_rotation(T_chain) @ _closest_rotation(T_link_visual)

        if cfg.debug:
            print(f"\n=== chain → {link_name} ===")
            if path:
                print("[joint chain]")
                for js in path:
                    q_used = float(cfg.q.get(js.name, 0.0))
                    ax = js.axis
                    print(f"  - {js.parent} --({js.name}, type={js.joint_type}, q={q_used:.6f}, axis=({ax[0]:.4f},{ax[1]:.4f},{ax[2]:.4f}))--> {js.child}")
            else:
                print("  (root link or no joints on path)")
            print("[matrices BEFORE closest_rotation]")
            _print_T_full("T_chain (raw)", T_chain)
            _print_T_full("T_link->visual (raw)", T_link_visual)
            print("[matrices AFTER closest_rotation]")
            _print_T_full("T_chain (closestR)", _closest_rotation(T_chain.copy()))
            _print_T_full("T_link->visual (closestR)", _closest_rotation(T_link_visual.copy()))
            _print_T_full("T_total (apply)", T_total)

            # Warn on unknown joint keys in q
            if cfg.q:
                unused = [k for k in cfg.q.keys() if k not in parser.model.joints]
                if unused:
                    print(f"[WARN] q contains joint names not in URDF and thus ignored: {unused}")

        ply = PlyData.read(ply_path)
        out_path = os.path.join(out_dir, f"{link_name}_gaussian_chain.ply")
        save_gaussian_with_transform(ply, out_path, T_total)
        saved[link_name] = out_path

    # Merge
    if saved and cfg.gaussian_out_name:
        try:
            merged_out = os.path.join(out_dir, cfg.gaussian_out_name)
            merge_gaussians_to_single_ply(list(saved.values()), merged_out)
            saved["_merged"] = merged_out
        except Exception as e:
            print(f"[error] merge failed: {e}")

    return saved

# --------------------- example ---------------------
if __name__ == "__main__":
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    object_path = os.path.join(project_root, "export", "grinder")  # edit
    cfg = RenderConfig(
        urdf_path=os.path.join(object_path, "urdf", "object.urdf"),
        mesh_root=os.path.join(object_path, "urdf", "meshes"),
        gauss_root=os.path.join(object_path, "gaussian"),
        link_to_gauss={
            "link_1": os.path.join(object_path, "gaussian", "gaussian_1.ply"),
            "link_2": os.path.join(object_path, "gaussian", "gaussian_2.ply"),
        },
        q={
            "joint_1_2": np.pi/2,
        },
        out_dir=os.path.join(object_path, "render"),
        gaussian_out_name="configure_2.ply"
    )
    out = render_gaussians_parent_to_child(cfg)
    print(out)