from dataclasses import dataclass, field
import os
import pymeshlab
import trimesh
import vedo
from pymeshlab import PercentageValue
from json_handler import JsonHandler

from functions import repair_mesh, flatten_bottom_hole, fill_bottom_hole

@dataclass
class RefinementConfig:
    """
    Centralizes all ms.* call parameters.
    """
    # do_flatten_bottom: bool = False
    do_flatten_bottom: bool = True

    # Toggle steps on/off
    steps: dict = field(default_factory=lambda: {
        "cleaning": True, # step-1
        "reconstruction": True, # step-2
        # "vertex_selection": False, # step-3
        "vertex_selection": True,
        "decimation": True, # step-4
        "remeshing": True, # step-5
        # "occlusion_repair": False, # step-6
        "occlusion_repair": True,
        "close_holes": True, # step-7
        "attribute_transfer": True, # step-8
    })

    params: dict = field(default_factory=lambda: {
        # 1) cleaning / components
        "meshing_remove_connected_component_by_diameter": {
            "mincomponentdiag": PercentageValue(20.0),
        },
        # 2) reconstruction
        "generate_surface_reconstruction_screened_poisson": {
            "depth": 8, # default = 10
            "fulldepth": 8, # default = 8
            # 'cgdepth': 0,
            # 'scale': 1.1,
            # 'samplespernode': 1.5,
            # 'pointweight': 4,
            # 'iters': 8,
            # 'confidence': False,
            'preclean': True,
            # 'threads': 16,
        },
        # 3) vertex selection (cut)
        "compute_selection_by_condition_per_vertex": {
            "condselect": "(z < -1e-6)",
        },
        # 4) decimation
        "meshing_decimation_quadric_edge_collapse": {
            "targetfacenum": 15000,
            "preservenormal": False,
        },
        # 5) remeshing
        "meshing_isotropic_explicit_remeshing": {
            "targetlen": PercentageValue(1.0),
            # 'iterations': 10,
            'adaptive': True,
            # 'selectedonly': False,
            # 'featuredeg': 30.0,
            # 'checksurfdist': True,
            # 'maxsurfdist': PercentageValue(1.0),
            # 'splitflag': True,
            # 'collapseflag': True,
            # 'swapflag': True,
            # 'smoothflag': True,
            # 'reprojectflag': True,
        },
        # 6) close holes
        "meshing_close_holes": {
            "maxholesize": 10000,
        },
        # 7) attribute transfer
        "transfer_attributes_per_vertex": {
            "sourcemesh": 1,
            "targetmesh": 0,
            "vertexsampling": False,
            "geomtransfer": False,
            "normaltransfer": True,
            "colortransfer": True,
            "upperbound": PercentageValue(5.0),
        },
    })


def debug_show_mesh(ms: pymeshlab.MeshSet, title: str):
    """Helper to visualize the current mesh in a vedo window."""
    if not isinstance(ms, pymeshlab.MeshSet) or ms.mesh_number() == 0:
        print(f"[Debug Viewer] Skipping: Invalid MeshSet for '{title}'")
        return

    print(f"[Debug Viewer] Showing: {title}")

    # PyMeshLab Mesh -> Trimesh -> Vedo Actor
    try:
        current_mesh = ms.current_mesh()
        verts = current_mesh.vertex_matrix()
        faces = current_mesh.face_matrix()

        if verts is None or faces is None or verts.size == 0 or faces.size == 0:
            print(f"[Debug Viewer] Skipping '{title}': No geometry to show.")
            return

        # Create a vedo actor with default lightblue color
        vedo_mesh = vedo.Mesh([verts, faces]).c("lightblue")

        # Try to apply vertex colors if they exist
        try:
            colors = current_mesh.vertex_color_matrix()
            if colors is not None and colors.size > 0:
                # Vedo expects colors in 0-255 range, uint8
                if colors.max() <= 1.0:
                    colors = (colors * 255).astype('uint8')
                vedo_mesh.pointcolors(colors[:, :3])  # Use RGB, ignore alpha if present
        except Exception:
            # Could fail if no colors exist, just ignore.
            pass

        # Show the mesh
        plt = vedo.Plotter(title=title, axes=1, size=(1800, 1200))
        plt.show(vedo_mesh, title).close()

    except Exception as e:
        print(f"[Debug Viewer] Error displaying '{title}': {e}")


def stage_refine(cfgs, debug_mode: bool = False):
    refinement_method = getattr(cfgs, "refinement_method", "pymeshlab")
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

    # Point2Mesh execution command
    cmd = [
        p2m_venv_python,
        os.path.join(p2m_dir, "main.py"),
        "--input-pc", mesh_in_dir,
        "--initial-mesh", mesh_in_dir,
        "--save-path", save_dir,
        "--iterations", str(getattr(cfgs, "point2mesh_iterations", 10)),
        "--gpu", "-1"
    ]

    print(f"[point2mesh]: Running command: {' '.join(cmd)}")
    import subprocess
    result = subprocess.run(cmd, cwd=p2m_dir, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[point2mesh warning]: point2mesh failed with stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        print("[point2mesh warning]: Falling back to PyMeshLab refinement.")
        run_pymeshlab_refinement(cfgs, debug_mode=debug_mode)
        return

    # Check output mesh
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


def run_pymeshlab_refinement(cfgs, debug_mode: bool = False):
    # Load configurations
    refCfgs = RefinementConfig()
    states = JsonHandler(cfgs.json_states_dir, auto_save=False)

    # Load meshes
    ms = pymeshlab.MeshSet()
    mesh_in_dir = states.transform.dirs.mesh
    ms.load_new_mesh(mesh_in_dir)
    if debug_mode: debug_show_mesh(ms, "0. Initial State")

    # --------------------------------------------------------------------------
    # Mesh Refinement Process
    # --------------------------------------------------------------------------

    # 1) Cleaning: remove small connected components
    if refCfgs.steps.get("cleaning", True):
        ms.meshing_remove_connected_component_by_diameter(
            **refCfgs.params["meshing_remove_connected_component_by_diameter"]
        )
        if debug_mode: debug_show_mesh(ms, "1. After Component Cleaning")

    # 2) Reconstruction: Screened Poisson
    if refCfgs.steps.get("reconstruction", True):
        ms.generate_surface_reconstruction_screened_poisson(
            **refCfgs.params["generate_surface_reconstruction_screened_poisson"]
        )
        if debug_mode: debug_show_mesh(ms, "2. After Poisson Reconstruction")

    # 3) Vertex selection (cut-off)
    if refCfgs.steps.get("vertex_selection", True):
        ms.compute_selection_by_condition_per_vertex(
            **refCfgs.params["compute_selection_by_condition_per_vertex"]
        )
        if ms.current_mesh().selected_vertex_number() > 0:
            ms.meshing_remove_selected_vertices()
        if debug_mode: debug_show_mesh(ms, "3. After Artifact Removal (z<0)")

    # 4) Decimation (edge collapse)
    if refCfgs.steps.get("decimation", True):
        ms.meshing_decimation_quadric_edge_collapse(
            **refCfgs.params["meshing_decimation_quadric_edge_collapse"]
        )
        if debug_mode: debug_show_mesh(ms, "4. After Simplification")

    # 5) Remeshing (isotropic explicit)
    if refCfgs.steps.get("remeshing", True):
        ms.meshing_isotropic_explicit_remeshing(
            **refCfgs.params["meshing_isotropic_explicit_remeshing"]
        )
        if debug_mode: debug_show_mesh(ms, "5. After Isotropic Remeshing")

        # AUX: recovery
        repair_mesh(ms)

    # Infill bottom occlusion
    if refCfgs.steps.get("occlusion_repair", True):
        if refCfgs.do_flatten_bottom:
            ms = flatten_bottom_hole(ms, target_z=0.0)
            ms = fill_bottom_hole(ms)
        if debug_mode: debug_show_mesh(ms, "6. After Occlusion Repair")

        # AUX: recovery
        repair_mesh(ms)

    # 6) Close holes
    if refCfgs.steps.get("close_holes", True):
        ms.meshing_close_holes(
            **refCfgs.params["meshing_close_holes"]
        )
        if debug_mode: debug_show_mesh(ms, "7. After Hole Closing")

    # AUX: recovery
    repair_mesh(ms)

    # 7) Restore vertex colors (attribute transfer)
    if refCfgs.steps.get("attribute_transfer", True):
        ms.load_new_mesh(mesh_in_dir) # This is the source mesh (index 1)
        ms.set_current_mesh(0) # Target mesh is the refined one

        ms.transfer_attributes_per_vertex(
            **refCfgs.params["transfer_attributes_per_vertex"]
        )
        if debug_mode: debug_show_mesh(ms, "8. After Attribute Restoration")

        ms.set_current_mesh(1)
        ms.delete_current_mesh()
        ms.set_current_mesh(0)

    # --------------------------------------------------------------------------
    # Save the Refined Mesh
    # --------------------------------------------------------------------------
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

