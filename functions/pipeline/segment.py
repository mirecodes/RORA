import os

import numpy as np
import pymeshlab
import trimesh

from json_handler import JsonHandler
from functions.math.graph import label_vertices
from functions.gui.bridge import ui
from functions.gui.models import group_fragments
from functions.visualize.plots import show_labels


# =============================================================================
# Stage (entry point)
# =============================================================================
def stage_segment(cfgs):
    """
    1) Part selection (UI): convex fragments → parts
    2) Vertex labeling of the refined mesh
    3) Persist vert_label.npy + states.segment.{parts_num, dirs.vert_label}
    """

    segCfgs = cfgs.params["segment"]

    print("=" * 60)
    print("[info] Starting stage_segment...")
    ui().plan([("load", "Load", True), ("select", "Part selection", True), ("label", "Vertex labeling", True),
               ("save", "Save", True)])
    ui().step("load")

    # load states & base mesh
    print("[info] Loading states and base mesh...")
    states = JsonHandler(cfgs.json_states_dir, auto_save=True)
    fragments = [trimesh.load(states.decompose.dirs.mesh[i]) for i in range(states.decompose.length)]

    ms = pymeshlab.MeshSet()
    mesh_in_dir = states.refine.dirs.mesh
    ms.load_new_mesh(mesh_in_dir)
    ms.set_current_mesh(0)
    current_mesh = ms.current_mesh()
    verts = current_mesh.vertex_matrix()
    faces = current_mesh.face_matrix().astype(np.int64)

    parts_num = cfgs.parts_num

    # part selection in the viewport
    ui().step("select")
    print("[info] Starting interactive part selection...")
    from functions.gui.scenes import PartSelectScene  # GUI-only import keeps this module importable headless
    owner = ui().interact(PartSelectScene([(f.vertices, f.faces) for f in fragments], verts, faces, parts_num))
    parts = group_fragments(fragments, owner, parts_num)
    print("[info] Part selection finished.")

    # --- Compact parts by removing empty ones (keeping index 0) ---
    if len(parts) > 1:
        new_parts = [parts[0]]
        for p in parts[1:]:
            if p:
                new_parts.append(p)

        if len(new_parts) != len(parts):
            print(f"[info] Removed {len(parts) - len(new_parts)} empty parts.")
            parts = new_parts
            parts_num = len(parts) - 1
            print(f"[info] Updated parts_num: {parts_num}")
    # -------------------------------------------------------------------

    if not any(parts) and parts_num > 0:
        print("[warn] No fragments assigned.")

    # vertex labels
    ui().step("label")
    print("[info] Classifying vertices...")
    vert_label = label_vertices(verts, parts, **segCfgs["labeling"]).astype(int)
    print("[info] Classification finished.")

    if cfgs.debug_mode:
        show_labels(verts, faces, vert_label)

    ui().step("save")
    # persist: per-vertex part labels of the refined mesh (states.refine.dirs.mesh vertex order)
    print("[info] Persisting states...")
    vert_label_path = os.path.join(cfgs.json_attr_dir, "vert_label.npy")
    np.save(vert_label_path, vert_label)
    states.segment = {}
    states.segment.parts_num = parts_num
    states.segment.dirs = {"vert_label": vert_label_path}
    print(f"[info] Vertex labels saved: {vert_label_path}")

    print("[info] stage_segment finished successfully.")
    print("=" * 60)
