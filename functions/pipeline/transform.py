import os
import numpy as np
import plyfile
import pymeshlab
import trimesh
from plyfile import PlyData, PlyElement
from json_handler import JsonHandler

from functions.gui.bridge import ui
from functions.utils.mesh import align_transform


# ----------------------- small linear algebra helpers ------------------------

def apply_Rt_points(P: np.ndarray, Rmat: np.ndarray, tvec: np.ndarray) -> np.ndarray:
    return (P @ Rmat.T) + tvec

def apply_R_normals(N: np.ndarray, Rmat: np.ndarray) -> np.ndarray:
    N2 = (N @ Rmat.T)
    N2 /= (np.linalg.norm(N2, axis=1, keepdims=True) + 1e-12)
    return N2

def _closest_rotation(M4: np.ndarray) -> np.ndarray:
    """Project the linear part to SO(3) (remove shear/scale)."""
    M = M4.copy()
    U, _, Vt = np.linalg.svd(M[:3, :3])
    R = U @ Vt
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1
        R = U @ Vt
    M[:3, :3] = R
    return M

# ---------------------------- quaternion helpers -----------------------------

def _R_to_quat(R: np.ndarray) -> np.ndarray:
    """Convert 3x3 rotation to quaternion (w,x,y,z)."""
    t = float(np.trace(R))
    if t > 0:
        r = np.sqrt(1.0 + t); w = 0.5 * r; r = 0.5 / r
        x = (R[2,1] - R[1,2]) * r
        y = (R[0,2] - R[2,0]) * r
        z = (R[1,0] - R[0,1]) * r
    else:
        i = int(np.argmax([R[0,0], R[1,1], R[2,2]]))
        if i == 0:
            r = np.sqrt(1.0 + R[0,0] - R[1,1] - R[2,2]); x = 0.5 * r; r = 0.5 / r
            y = (R[0,1] + R[1,0]) * r; z = (R[0,2] + R[2,0]) * r; w = (R[2,1] - R[1,2]) * r
        elif i == 1:
            r = np.sqrt(1.0 - R[0,0] + R[1,1] - R[2,2]); y = 0.5 * r; r = 0.5 / r
            x = (R[0,1] + R[1,0]) * r; z = (R[1,2] + R[2,1]) * r; w = (R[0,2] - R[2,0]) * r
        else:
            r = np.sqrt(1.0 - R[0,0] - R[1,1] + R[2,2]); z = 0.5 * r; r = 0.5 / r
            x = (R[0,2] + R[2,0]) * r; y = (R[1,2] + R[2,1]) * r; w = (R[1,0] - R[0,1]) * r
    q = np.array([w, x, y, z], dtype=np.float64)
    q /= (np.linalg.norm(q) + 1e-12)
    return q

def _quat_mul(qR: np.ndarray, qG: np.ndarray) -> np.ndarray:
    """Quaternion multiply qR * qG, both (w,x,y,z)."""
    w1, x1, y1, z1 = qR
    w2, x2, y2, z2 = qG
    return np.array([
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2
    ], dtype=np.float64)

def _rotate_gaussian_quats(vertex_el, Rmat: np.ndarray) -> bool:
    """
    If quaternion fields exist, rotate them by R: q' = q_R * q.
    Supports fields (rot_0..3) or (qw,qx,qy,qz).
    """
    names = vertex_el.data.dtype.names or ()
    quat_R = _R_to_quat(Rmat)
    changed = False

    if all(f in names for f in ('rot_0', 'rot_1', 'rot_2', 'rot_3')):
        q = np.stack([vertex_el['rot_0'], vertex_el['rot_1'], vertex_el['rot_2'], vertex_el['rot_3']], axis=1).astype(np.float64)
        q2 = np.vstack([_quat_mul(quat_R, qi) for qi in q])
        vertex_el['rot_0'] = q2[:, 0].astype(vertex_el['rot_0'].dtype)
        vertex_el['rot_1'] = q2[:, 1].astype(vertex_el['rot_1'].dtype)
        vertex_el['rot_2'] = q2[:, 2].astype(vertex_el['rot_2'].dtype)
        vertex_el['rot_3'] = q2[:, 3].astype(vertex_el['rot_3'].dtype)
        changed = True

    if all(f in names for f in ('qw', 'qx', 'qy', 'qz')):
        q = np.stack([vertex_el['qw'], vertex_el['qx'], vertex_el['qy'], vertex_el['qz']], axis=1).astype(np.float64)
        q2 = np.vstack([_quat_mul(quat_R, qi) for qi in q])
        vertex_el['qw'] = q2[:, 0].astype(vertex_el['qw'].dtype)
        vertex_el['qx'] = q2[:, 1].astype(vertex_el['qx'].dtype)
        vertex_el['qy'] = q2[:, 2].astype(vertex_el['qy'].dtype)
        vertex_el['qz'] = q2[:, 3].astype(vertex_el['qz'].dtype)
        changed = True

    return changed


# -------------------------- mesh export with T applied -----------------------

def save_mesh_with_transform(ms_mesh: pymeshlab.Mesh, out_path: str, T4: np.ndarray):
    V = ms_mesh.vertex_matrix().astype(np.float64)
    F = ms_mesh.face_matrix().astype(np.int64)

    T4 = _closest_rotation(T4)  # ensure pure rotation on normals
    Rmat = T4[:3, :3].astype(np.float64)
    tvec = T4[:3, 3].astype(np.float64)

    V2 = apply_Rt_points(V, Rmat, tvec)

    # normals
    vnorm = ms_mesh.vertex_normal_matrix()
    if vnorm is not None and len(vnorm) == len(V):
        vnorm = apply_R_normals(vnorm.astype(np.float64), Rmat)
    else:
        vnorm = None

    # colors
    vcols = ms_mesh.vertex_color_matrix() if ms_mesh.has_vertex_color() else None

    tm = trimesh.Trimesh(vertices=V2, faces=F, process=False)

    if vnorm is not None:
        tm.vertex_normals = vnorm
    if vcols is not None:
        rgb = np.clip(vcols[:, :3] * 255.0, 0, 255).astype(np.uint8)
        alpha = 255 * np.ones((rgb.shape[0], 1), np.uint8)
        tm.visual.vertex_colors = np.hstack([rgb, alpha])

    tm.export(out_path)


# ---------------------- gaussian PLY export with T applied -------------------

def _write_ply_preserve_all(ply_in: PlyData, vertex_el, out_path: str):
    """Write PLY preserving all elements/metadata; replace only 'vertex'."""
    new_elements = []
    for el in ply_in.elements:
        if el.name == 'vertex':
            # replace with updated vertex element
            new_elements.append(PlyElement.describe(vertex_el.data, 'vertex'))
        else:
            new_elements.append(el)
    new_ply = PlyData(new_elements, text=ply_in.text)
    new_ply.byte_order = ply_in.byte_order
    new_ply.comments = list(ply_in.comments)
    new_ply.obj_info = list(ply_in.obj_info)
    new_ply.write(out_path)

def save_gaussian_with_transform(ply: plyfile.PlyData, gaussian_out_path: str, T4: np.ndarray):
    v = ply['vertex']
    names = v.data.dtype.names or ()

    T4 = _closest_rotation(T4)  # ensure pure rotation in the applied part
    Rmat = T4[:3, :3].astype(np.float64)
    tvec = T4[:3, 3].astype(np.float64)

    # positions
    if all(k in names for k in ('x', 'y', 'z')):
        P = np.stack([v['x'], v['y'], v['z']], axis=1).astype(np.float64)
        P2 = apply_Rt_points(P, Rmat, tvec)
        v['x'] = P2[:, 0].astype(v['x'].dtype)
        v['y'] = P2[:, 1].astype(v['y'].dtype)
        v['z'] = P2[:, 2].astype(v['z'].dtype)

    # normals (if present)
    if all(k in names for k in ('nx', 'ny', 'nz')):
        N = np.stack([v['nx'], v['ny'], v['nz']], axis=1).astype(np.float64)
        N2 = apply_R_normals(N, Rmat)
        v['nx'] = N2[:, 0].astype(v['nx'].dtype)
        v['ny'] = N2[:, 1].astype(v['ny'].dtype)
        v['nz'] = N2[:, 2].astype(v['nz'].dtype)

    # quaternions (if present)
    _ = _rotate_gaussian_quats(v, Rmat)

    # write preserving other elements/metadata
    _write_ply_preserve_all(ply, v, gaussian_out_path)


# ------------------------------- main stage ----------------------------------

def stage_transform(cfgs):
    tf_cfgs = cfgs.params["transform"]
    ui().plan([("load", "Load", True), ("auto", "Auto-align", bool(tf_cfgs["use_auto_alignment"])),
               ("manual", "Manual adjust", True), ("save", "Save", True)])

    ui().step("load")
    ms = pymeshlab.MeshSet()
    try:
        ms.load_new_mesh(cfgs.mesh_in_dir)
        ms.load_new_mesh(cfgs.gaussian_in_dir)
        ms.set_current_mesh(0)
    except pymeshlab.PyMeshLabException:
        print(f"[error]: Failed to find mesh. dir={cfgs.in_dir}")
        raise FileNotFoundError()

    mesh = ms.mesh(0)
    
    if tf_cfgs["use_auto_alignment"]:
        ui().step("auto")
        initial_transform = align_transform(ms)  # 4x4
        if initial_transform is None:
            print("[Warning] Auto-alignment failed. Using Identity.")
            initial_transform = np.eye(4)
    else:
        print("[Info] Auto-alignment disabled. Using Identity.")
        initial_transform = np.eye(4)

    # Manual adjustment in the viewport; rotations pivot on the world origin (ground plane stays put)
    ui().step("manual")
    verts, faces = mesh.vertex_matrix(), mesh.face_matrix()
    R0 = initial_transform[:3, :3].astype(np.float64)
    t0 = initial_transform[:3, 3].astype(np.float64)
    verts_vis = apply_Rt_points(verts.astype(np.float64), R0, t0)
    point_colors = cell_colors = None
    if mesh.has_vertex_color():
        point_colors = (mesh.vertex_color_matrix()[:, :3] * 255).astype(np.uint8)
    elif mesh.has_face_color():
        cell_colors = (mesh.face_color_matrix()[:, :3] * 255).astype(np.uint8)
    from functions.gui.scenes import AlignScene  # GUI-only import keeps this module importable headless
    fine_M = ui().interact(AlignScene(verts_vis, faces, point_colors, cell_colors))

    # accumulate transforms: project each to pure rotation before composing
    ui().step("save")
    fine_M = _closest_rotation(np.asarray(fine_M, dtype=float))
    initial_transform = _closest_rotation(initial_transform)

    # NOTE: If orientation is still off, try swapping the order below.
    total_T = fine_M @ initial_transform

    # save mesh
    os.makedirs(cfgs.mesh_working_dir, exist_ok=True)
    mesh_out = os.path.join(cfgs.mesh_working_dir, f"transformed_mesh.{cfgs.extension}")
    save_mesh_with_transform(mesh, mesh_out, total_T)

    # save gaussian (positions + normals + quats, preserve other PLY elements)
    gaussian_in = cfgs.gaussian_in_dir
    ply = PlyData.read(gaussian_in)
    gaussian_out = os.path.join(cfgs.mesh_working_dir, f"transformed_gaussian.{cfgs.extension}")
    save_gaussian_with_transform(ply, gaussian_out, total_T)

    # persist state
    states = JsonHandler(cfgs.json_states_dir, auto_save=True)
    states.transform = {}
    states.transform.matrix = total_T.tolist()
    states.transform.dirs = {"mesh": mesh_out, "gaussian": gaussian_out}
    ms.clear()

    return


import os
import numpy as np
from plyfile import PlyData
import pymeshlab
import trimesh

# ----- assumes the following helpers already exist in your module -----
# _closest_rotation(M4), save_mesh_with_transform(ms_mesh, out_path, T4)
# save_gaussian_with_transform(ply: PlyData, gaussian_out_path: str, T4: np.ndarray)
from json_handler import JsonHandler


def _load_T_from_states(states_dir: str) -> np.ndarray:
    """Load 4x4 transform from states JSON; validate shape and normalize to pure rotation."""
    states = JsonHandler(states_dir, auto_save=False)
    try:
        T_list = states.transform.matrix
    except Exception:
        raise FileNotFoundError("[error]: states.transform.matrix not found. Run stage_transform first.")
    T = np.asarray(T_list, dtype=np.float64)
    if T.shape != (4, 4):
        raise ValueError(f"[error]: Invalid transform shape: {T.shape}, expected (4,4)")
    return T


def restore_transform(cfgs, *, overwrite: bool = True, suffix: str = "restored"):
    """
    Re-apply the previously saved transform (states.transform.matrix) to the current
    mesh_in_dir and gaussian_in_dir, writing outputs to cfgs.mesh_working_dir.
    - overwrite: if True, overwrite the same filenames used by stage_transform
    - suffix: filename suffix when overwrite=False (default: *_restored.ext)
    """
    ui().plan([("load", "Load", True), ("restore", "Restore", True), ("save", "Save", True)])
    ui().step("load")

    # 1) Load transform from states
    T4 = _load_T_from_states(cfgs.json_states_dir)
    T4 = _closest_rotation(T4)  # safety: remove shear/scale

    # 2) Prepare IO
    os.makedirs(cfgs.mesh_working_dir, exist_ok=True)

    # Output names
    if overwrite:
        mesh_out = os.path.join(cfgs.mesh_working_dir, f"transformed_mesh.{cfgs.extension}")
        gaussian_out = os.path.join(cfgs.mesh_working_dir, f"transformed_gaussian.{cfgs.extension}")
    else:
        mesh_out = os.path.join(cfgs.mesh_working_dir, f"transformed_mesh_{suffix}.{cfgs.extension}")
        gaussian_out = os.path.join(cfgs.mesh_working_dir, f"transformed_gaussian_{suffix}.{cfgs.extension}")

    # 3) Load inputs
    ms = pymeshlab.MeshSet()
    try:
        ms.load_new_mesh(cfgs.mesh_in_dir)         # original mesh input
    except pymeshlab.PyMeshLabException as e:
        raise FileNotFoundError(f"[error]: Failed to load mesh: {cfgs.mesh_in_dir}") from e

    # 4) Apply & save mesh
    ui().step("restore")
    mesh = ms.current_mesh()
    save_mesh_with_transform(mesh, mesh_out, T4)

    # 5) Apply & save gaussian (if available)
    gaussian_path = getattr(cfgs, "gaussian_in_dir", None)
    if gaussian_path is not None and os.path.isfile(gaussian_path):
        try:
            ply = PlyData.read(gaussian_path)
            save_gaussian_with_transform(ply, gaussian_out, T4)
        except Exception as e:
            # Do not hard-fail on gaussian; surface result is still useful.
            print(f"[error]: failed to process gaussian: {gaussian_path} ({e})")
            gaussian_out = None
    else:
        print(f"[error]: gaussian_in_dir missing or not a file: {gaussian_path}")
        gaussian_out = None

    # 6) Persist outputs (do not overwrite matrix; only update dirs)
    ui().step("save")
    states = JsonHandler(cfgs.json_states_dir, auto_save=True)
    if not hasattr(states, "transform") or states.transform is None:
        states.transform = {}
    # keep matrix as-is; update output paths for this restore
    if gaussian_out is not None:
        states.transform.dirs_restore = {"mesh": mesh_out, "gaussian": gaussian_out}
    else:
        states.transform.dirs_restore = {"mesh": mesh_out}

    # 7) Cleanup
    try:
        ms.clear()
    except Exception:
        pass