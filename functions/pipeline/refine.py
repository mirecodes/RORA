import os
import numpy as np
import pymeshlab
import trimesh
from pymeshlab import PercentageValue
from json_handler import JsonHandler

from functions.utils.mesh import repair_mesh, flatten_bottom_hole, fill_bottom_hole
from functions.gui.bridge import ui
from functions.visualize.plots import show_meshset


def _pct(params: dict) -> dict:
    """Convert "N%" strings from parameters_cfg.yml into pymeshlab.PercentageValue(N)."""
    return {k: PercentageValue(float(v[:-1])) if isinstance(v, str) and v.endswith("%") else v
            for k, v in params.items()}


def stage_refine(cfgs, debug_mode: bool = False):
    refinement_method = cfgs.params["refine"]["method"]
    print(f"[info]: Refinement stage using method: '{refinement_method}'")

    if refinement_method == "point2mesh":
        run_point2mesh_refinement(cfgs, debug_mode=debug_mode)
    elif refinement_method == "pymeshlab_then_point2mesh":
        print("[info]: Step 1/2 - Running PyMeshLab Refinement...")
        run_pymeshlab_refinement(cfgs, debug_mode=debug_mode)
        states = JsonHandler(cfgs.json_states_dir, auto_save=False)
        pymeshlab_refined_mesh = states.refine.dirs.mesh
        print(f"[info]: Step 2/2 - Running Point2Mesh Refinement on PyMeshLab result ({pymeshlab_refined_mesh})...")
        run_point2mesh_refinement(cfgs, input_mesh_path=pymeshlab_refined_mesh, debug_mode=debug_mode)
    else:
        run_pymeshlab_refinement(cfgs, debug_mode=debug_mode)


def run_point2mesh_refinement(cfgs, input_mesh_path: str = None, debug_mode: bool = False):
    ui().plan([("p2m_prepare", "Prepare", True), ("point2mesh", "point2mesh", True), ("p2m_save", "Save", True)])
    ui().step("p2m_prepare")
    p2m_cfgs = cfgs.params["refine"]["point2mesh"]
    states = JsonHandler(cfgs.json_states_dir, auto_save=False)
    raw_mesh_in = input_mesh_path if input_mesh_path else states.transform.dirs.mesh
    mesh_in_dir = os.path.abspath(raw_mesh_in)

    # Base directory for point2mesh
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p2m_dir = os.path.join(project_root, "submodules", "point2mesh")
    p2m_venv_python = os.path.join(p2m_dir, ".venv", "bin", "python")

    if not os.path.exists(p2m_venv_python):
        # Fallback to system/current python if .venv python is missing
        p2m_venv_python = "python"

    mesh_out_dir = os.path.abspath(os.path.join(cfgs.mesh_working_dir, f"refined_mesh.{cfgs.extension}"))
    save_dir = os.path.abspath(os.path.join(cfgs.mesh_working_dir, "point2mesh_out"))
    os.makedirs(save_dir, exist_ok=True)

    # Convert to the formats point2mesh reads natively: initial mesh (.obj), point cloud with normals (.xyz)
    init_obj = os.path.join(save_dir, "initial_mesh.obj")
    input_xyz = os.path.join(save_dir, "input_pc.xyz")
    tm = trimesh.load(mesh_in_dir, force="mesh", process=False)
    tm.export(init_obj)
    np.savetxt(input_xyz, np.hstack([tm.vertices, tm.vertex_normals]), fmt="%.6f")

    # Point2Mesh execution command (runner applies runtime fixes; the submodule stays unmodified)
    cmd = [
        p2m_venv_python,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "point2mesh_runner.py"),
        "--input-pc", input_xyz,
        "--initial-mesh", init_obj,
        "--save-path", save_dir,
        "--iterations", str(p2m_cfgs["iterations"]),
        "--gpu", str(p2m_cfgs["gpu"])
    ]

    print(f"[point2mesh]: Running command: {' '.join(cmd)}")
    ui().step("point2mesh")
    import subprocess
    proc = subprocess.Popen(cmd, cwd=p2m_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1)
    for line in proc.stdout:  # stream to the terminal / log panel while it runs
        print(f"[point2mesh] {line.rstrip()}")
    if proc.wait() != 0:
        print(f"[point2mesh warning]: point2mesh exited with code {proc.returncode} (output above).")
        print("[point2mesh warning]: Falling back to PyMeshLab refinement.")
        run_pymeshlab_refinement(cfgs, debug_mode=debug_mode)
        return

    # Check output mesh
    ui().step("p2m_save")
    recon_obj = os.path.join(save_dir, "last_recon.obj")
    if os.path.exists(recon_obj):
        # Convert OBJ output to target extension (e.g., PLY) using pymeshlab
        ms = pymeshlab.MeshSet()
        ms.load_new_mesh(recon_obj)
        ms.save_current_mesh(mesh_out_dir)
        ms.clear()
        print(f"[point2mesh]: Successfully generated refined mesh at {mesh_out_dir}")
    else:
        print(f"[point2mesh warning]: {recon_obj} not found. Falling back to PyMeshLab.")
        run_pymeshlab_refinement(cfgs, debug_mode=debug_mode)
        return

    states = JsonHandler(cfgs.json_states_dir, auto_save=True)
    states.refine = {}
    states.refine.dirs = {"mesh": mesh_out_dir}


PYMESHLAB_STEPS = [("cleaning", "① Cleaning"), ("reconstruction", "② Poisson"),
                   ("vertex_selection", "③ Artifact removal"), ("decimation", "④ Simplification"),
                   ("remeshing", "⑤ Remeshing"), ("occlusion_repair", "⑥ Occlusion repair"),
                   ("close_holes", "⑦ Hole closing"), ("attribute_transfer", "⑧ Attribute restoration")]


def run_pymeshlab_refinement(cfgs, debug_mode: bool = False):
    # Load configurations
    refCfgs = cfgs.params["refine"]["pymeshlab"]
    enabled = {k: bool(refCfgs["steps"].get(k, True)) for k, _ in PYMESHLAB_STEPS}
    ui().plan([("load", "Load", True)] + [(k, label, enabled[k]) for k, label in PYMESHLAB_STEPS]
              + [("save", "Save", True)])
    ui().step("load")
    states = JsonHandler(cfgs.json_states_dir, auto_save=False)

    # Load meshes
    ms = pymeshlab.MeshSet()
    mesh_in_dir = states.transform.dirs.mesh
    ms.load_new_mesh(mesh_in_dir)
    if debug_mode: show_meshset(ms, "0. Initial State")

    # --------------------------------------------------------------------------
    # Mesh Refinement Process
    # --------------------------------------------------------------------------

    # 1) Cleaning: remove small connected components
    if refCfgs["steps"].get("cleaning", True):
        ui().step("cleaning")
        ms.meshing_remove_connected_component_by_diameter(
            **_pct(refCfgs["params"]["meshing_remove_connected_component_by_diameter"])
        )
        if debug_mode: show_meshset(ms, "1. After Component Cleaning")

    # 2) Reconstruction: Screened Poisson
    if refCfgs["steps"].get("reconstruction", True):
        ui().step("reconstruction")
        ms.generate_surface_reconstruction_screened_poisson(
            **_pct(refCfgs["params"]["generate_surface_reconstruction_screened_poisson"])
        )
        if debug_mode: show_meshset(ms, "2. After Poisson Reconstruction")

    # 3) Vertex selection (cut-off)
    if refCfgs["steps"].get("vertex_selection", True):
        ui().step("vertex_selection")
        ms.compute_selection_by_condition_per_vertex(
            **_pct(refCfgs["params"]["compute_selection_by_condition_per_vertex"])
        )
        if ms.current_mesh().selected_vertex_number() > 0:
            ms.meshing_remove_selected_vertices()
        if debug_mode: show_meshset(ms, "3. After Artifact Removal (z<0)")

    # 4) Decimation (edge collapse)
    if refCfgs["steps"].get("decimation", True):
        ui().step("decimation")
        ms.meshing_decimation_quadric_edge_collapse(
            **_pct(refCfgs["params"]["meshing_decimation_quadric_edge_collapse"])
        )
        if debug_mode: show_meshset(ms, "4. After Simplification")

    # 5) Remeshing (isotropic explicit)
    if refCfgs["steps"].get("remeshing", True):
        ui().step("remeshing")
        ms.meshing_isotropic_explicit_remeshing(
            **_pct(refCfgs["params"]["meshing_isotropic_explicit_remeshing"])
        )
        if debug_mode: show_meshset(ms, "5. After Isotropic Remeshing")

        # AUX: recovery
        repair_mesh(ms)

    # Infill bottom occlusion
    if refCfgs["steps"].get("occlusion_repair", True):
        ui().step("occlusion_repair")
        if refCfgs["do_flatten_bottom"]:
            ms = flatten_bottom_hole(ms, target_z=0.0)
            ms = fill_bottom_hole(ms)
        if debug_mode: show_meshset(ms, "6. After Occlusion Repair")

        # AUX: recovery
        repair_mesh(ms)

    # 6) Close holes
    if refCfgs["steps"].get("close_holes", True):
        ui().step("close_holes")
        ms.meshing_close_holes(
            **_pct(refCfgs["params"]["meshing_close_holes"])
        )
        if debug_mode: show_meshset(ms, "7. After Hole Closing")

    # AUX: recovery
    repair_mesh(ms)

    # 7) Restore vertex colors (attribute transfer)
    if refCfgs["steps"].get("attribute_transfer", True):
        ui().step("attribute_transfer")
        ms.load_new_mesh(mesh_in_dir) # This is the source mesh (index 1)
        ms.set_current_mesh(0) # Target mesh is the refined one

        ms.transfer_attributes_per_vertex(
            **_pct(refCfgs["params"]["transfer_attributes_per_vertex"])
        )
        if debug_mode: show_meshset(ms, "8. After Attribute Restoration")

        ms.set_current_mesh(1)
        ms.delete_current_mesh()
        ms.set_current_mesh(0)

    # --------------------------------------------------------------------------
    # Save the Refined Mesh
    # --------------------------------------------------------------------------
    ui().step("save")
    mesh_out_dir = os.path.join(cfgs.mesh_working_dir, f"refined_mesh.{cfgs.extension}")
    ms.save_current_mesh(mesh_out_dir)

    # Save intermediate state into JSON
    states = JsonHandler(cfgs.json_states_dir, auto_save=True)
    states.refine = {}
    states.refine.dirs = {"mesh": mesh_out_dir}

    try:
        ms.clear()
    except Exception:
        pass

    return

