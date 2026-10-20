import os

import coacd
import pymeshlab
import trimesh

from json_handler import JsonHandler

from functions.gui.bridge import ui


def stage_decompose(cfgs):
    ui().plan([("load", "Load", True), ("coacd", "CoACD", True), ("save", "Save fragments", True)])
    ui().step("load")
    states = JsonHandler(cfgs.json_states_dir, auto_save=True)

    # Load mesh data
    ms = pymeshlab.MeshSet()

    mesh_in_dir = states.refine.dirs.mesh
    ms.load_new_mesh(mesh_in_dir)
    mesh = ms.mesh(0)

    verts = mesh.vertex_matrix()
    faces = mesh.face_matrix()
    mesh = coacd.Mesh(verts, faces)

    # Parameters: cfgs/parameters_cfg.yml -> decompose.coacd (kwargs of coacd.run_coacd)
    params = cfgs.params["decompose"]["coacd"]
    print(f"[info] Running CoACD with parameters: {params}")

    # Run convex decomposition
    ui().step("coacd")
    fragments = coacd.run_coacd(mesh, **params)

    # Save intermediate state into the json file
    ui().step("save")
    states.decompose = {}
    states.decompose.length = len(fragments)
    states.decompose.dirs = {
        "mesh": list()
    }

    # Save each convex fragment with index suffix
    os.makedirs(os.path.dirname(cfgs.mesh_working_dir), exist_ok=True)

    for i, fragment in enumerate(fragments, start=1):
        tri = trimesh.Trimesh(vertices=fragment[0], faces=fragment[1], process=False)
        fname = f"fragment_{i}.{cfgs.extension}"
        decompose_dir = os.path.join(cfgs.mesh_working_dir, fname)
        tri.export(decompose_dir)
        states.decompose.dirs.mesh.append(decompose_dir)

    try:
        ms.clear()
    except Exception:
        pass

    return