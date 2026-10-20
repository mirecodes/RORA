import os
import sys
from pathlib import Path

# Add project root to python path to resolve local packages
project_root = str(Path(__file__).resolve().parents[2])
if project_root not in sys.path:
    sys.path.append(project_root)

from dataclasses import dataclass, field

import pymeshlab
from json_handler import JsonHandler

from functions import stage_transform, stage_refine, stage_decompose, stage_segment, stage_articulate, stage_bind, \
    restore_transform
from functions.utils.config import load_cfg, load_params


@dataclass
class SystemConfigs():
    """Built from cfgs/object_cfg.yml (what to process) and cfgs/parameters_cfg.yml + profile (how)."""
    obj: dict = field(default_factory=lambda: load_cfg("object_cfg"))
    params: dict = field(default_factory=lambda: load_params())
    root_dir: str = field(default=project_root, init=False)

    def __post_init__(self):
        # Pipeline switches
        pipe = self.params["pipeline"]
        self.stages = pipe["stages"]
        self.restore_align = pipe["restore_align"]
        self.debug_mode = pipe["debug_mode"]
        self.urdf_use_original_coordinates = pipe["urdf_use_original_coordinates"]

        # Object
        self.object_name = self.obj["object_name"]
        self.extension = self.obj["extension"]
        self.categories_num = self.obj["parts"]["num"]

        # Fundamental directories
        self.in_dir = os.path.join(self.root_dir, "data", "objects", self.object_name)
        self.out_dir = os.path.join(self.root_dir, "export", self.object_name)
        self.working_dir = os.path.join(self.root_dir, "working", self.object_name)

        # Functional directories
        self.json_attr_dir = os.path.join(self.working_dir, "attributes")
        self.mesh_working_dir = os.path.join(self.working_dir, "meshes")
        self.json_states_dir = os.path.join(self.json_attr_dir, "states.json")

        self.urdf_working_dir = os.path.join(self.working_dir, "urdf")
        self.urdf_out_dir = os.path.join(self.out_dir, "urdf")
        self.gaussian_out_dir = os.path.join(self.out_dir, "gaussian")

        self.mesh_in_dir = os.path.join(self.in_dir, f"mesh.{self.extension}")
        self.gaussian_in_dir = os.path.join(self.in_dir, f"gaussian.{self.extension}")

        # Create directories if necessary
        self.create_directories()

    def create_directories(self):
        dirs_to_create = [
            self.out_dir,
            self.working_dir,
            self.json_attr_dir,
            self.mesh_working_dir,
            self.urdf_working_dir,
            self.urdf_out_dir,
            self.gaussian_out_dir,
        ]

        for path in dirs_to_create:
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as e:
                print(f"[error]: Failed to create directory {path}: {e}")


import time


def execute_pipeline(cfgs: SystemConfigs):
    print("[info]: Execute the object importing pipeline")
    
    import functions
    functions.total_gui_time = 0.0

    stages_time = {}
    pipeline_start = time.time()

    if cfgs.stages["align"]:
        start_time = time.time()
        if cfgs.restore_align:
            restore_transform(cfgs)
            print("[info]: Restoring the alignment")
            stages_time["Alignment/Restore"] = time.time() - start_time
        else:
            stage_transform(cfgs)
            print("[info]: Running the alignment stage")
            stages_time["Alignment"] = time.time() - start_time

    if cfgs.stages["refine"]:
        print("[info]: Running the refinement stage")
        start_time = time.time()
        stage_refine(cfgs, debug_mode=cfgs.debug_mode)
        stages_time["Refinement"] = time.time() - start_time

    if cfgs.stages["decompose"]:
        print("[info]: Running the decomposition stage")
        start_time = time.time()
        stage_decompose(cfgs)
        stages_time["Decomposition"] = time.time() - start_time

    if cfgs.stages["segment"]:
        print("[info]: Running the segmentation stage")
        start_time = time.time()
        stage_segment(cfgs)
        stages_time["Segmentation"] = time.time() - start_time

    if cfgs.stages["articulate"]:
        print("[info]: Running the articulation stage")
        start_time = time.time()
        stage_articulate(cfgs)
        stages_time["Articulation"] = time.time() - start_time

    if cfgs.stages["bind"]:
        print("[info]: Running the binding stage")
        start_time = time.time()
        stage_bind(cfgs)
        stages_time["Binding"] = time.time() - start_time

    total_time = time.time() - pipeline_start
    gui_time = functions.total_gui_time
    processing_time = max(0.0, total_time - gui_time)

    print("\n" + "=" * 40)
    print(f"{'Pipeline Execution Summary':^40}")
    print("=" * 40)
    for stage_name, duration in stages_time.items():
        print(f"- {stage_name} stage: {duration:.2f}s")
    print("-" * 40)
    print(f"- Time spent in User GUI: {gui_time:.2f}s")
    print(f"- Time spent in Processing (Waiting): {processing_time:.2f}s")
    print("-" * 40)
    print(f"Total elapsed time: {total_time:.2f}s")
    print("=" * 40 + "\n")



def load_from_saves(cfgs: SystemConfigs, stage: str):
    states = JsonHandler(cfgs.json_states_dir, auto_save=False)
    try:
        ms = pymeshlab.MeshSet()
        mesh_dir, gaussian_dir = cfgs.mesh_in_dir, cfgs.gaussian_in_dir

        if stage == "transform":
            mesh_dir = states.transform.dirs.mesh
            gaussian_dir = states.transform.dirs.gaussian
        elif stage == "refine":
            mesh_dir = states.refine.dirs.mesh
            gaussian_dir = states.transform.dirs.gaussian
        elif stage == "decompose":
            mesh_dir = states.refine.dirs.mesh
            gaussian_dir = states.transform.dirs.gaussian
        elif stage == "segment":
            mesh_dir = states.refine.dirs.mesh
            gaussian_dir = states.transform.dirs.gaussian

        ms.load_new_mesh(mesh_dir)
        ms.load_new_mesh(gaussian_dir)
        ms.set_current_mesh(0)
        return ms

    except pymeshlab.PyMeshLabException:
        print(f"[error]: Failed to find mesh in directory. dir={cfgs.in_dir}")


if __name__ == "__main__":
    execute_pipeline(cfgs=SystemConfigs())
