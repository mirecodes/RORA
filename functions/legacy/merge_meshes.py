import os
import glob
from dataclasses import dataclass, field
from typing import Tuple, Optional, Dict

import trimesh


@dataclass
class SystemConfig:
    # --------------------------------------------------------------------------
    # 1. User settings
    # --------------------------------------------------------------------------
    # Base path of source meshes to merge
    # e.g. 'out/convex_decomp/refined_bonsai_pot' matches
    # 'refined_bonsai_pot_1.ply', 'refined_bonsai_pot_2.ply', ...
    input_mesh_base_path: str = os.path.abspath("../out/convex_decomp/refined_spray")

    # Output dir for merged meshes
    output_dir: str = os.path.abspath("out/merged_meshes")

    # Mesh groups to merge (1-based part numbers).
    # e.g. ((1, 2), (3, 4, 6), (5, 7)) -> merge 1,2; merge 3,4,6; ...
    # None: do nothing.
    mesh_groups: Optional[Tuple[Tuple[int, ...], ...]] = ((1, 2, 3, 4, 5, 7, 8), (6, 9))

    # --------------------------------------------------------------------------
    # 2. Derived settings
    # --------------------------------------------------------------------------
    root_dir: str = field(default_factory=lambda: os.path.abspath(os.path.join(os.path.dirname(__file__))),
                          init=False)

    def __post_init__(self):
        # Create output dir if missing
        os.makedirs(self.output_dir, exist_ok=True)
        # Make absolute
        self.input_mesh_base_path = os.path.join(self.root_dir, self.input_mesh_base_path)
        self.output_dir = os.path.join(self.root_dir, self.output_dir)


def merge_meshes_by_group(cfg: SystemConfig):
    """
    Merge and save mesh files per configured group.
    """
    if not cfg.mesh_groups:
        print("Warning: No mesh groups are defined in the configuration. Exiting.")
        return

    # 1. Find all decomposed part files
    # matching '_*.ply' via glob.
    all_part_paths = sorted(glob.glob(f"{cfg.input_mesh_base_path}_*.ply"))

    if not all_part_paths:
        print(f"Error: No decomposed parts found with base path: {cfg.input_mesh_base_path}")
        return

    # 2. Map part number -> file path
    part_path_map: Dict[int, str] = {}
    for path in all_part_paths:
        try:
            # Parse number from filename (e.g. refined_bonsai_pot_12.ply -> 12)
            filename = os.path.basename(path)
            num_str = filename.split('_')[-1].split('.')[0]
            part_num = int(num_str)
            part_path_map[part_num] = path
        except (ValueError, IndexError):
            print(f"Warning: Could not parse part number from filename: {path}")

    print(f"Found {len(part_path_map)} individual mesh parts.")

    # 3. Merge and save each group
    output_base_name = os.path.basename(cfg.input_mesh_base_path)

    for group in cfg.mesh_groups:
        print(f"\nProcessing group: {group}")
        meshes_to_merge = []

        # Load meshes in this group
        for part_num in group:
            if part_num in part_path_map:
                mesh_path = part_path_map[part_num]
                print(f"-> Loading part {part_num} from: {mesh_path}")
                mesh = trimesh.load(mesh_path, force="mesh")
                meshes_to_merge.append(mesh)
            else:
                print(f"Warning: Part {part_num} not found. Skipping.")

        # Proceed only if there are meshes to merge
        if len(meshes_to_merge) >= 1:
            print(f"-> Merging {len(meshes_to_merge)} meshes...")
            # Combine into one mesh
            combined_mesh = trimesh.util.concatenate(meshes_to_merge)

            # Name file after the group's smallest number
            output_part_number = min(group)
            out_filename = f"{output_base_name}_merged_{output_part_number}.ply"
            out_path = os.path.join(cfg.output_dir, out_filename)

            # Export merged mesh
            combined_mesh.export(out_path)
            print(f"Saved merged mesh for group {group} to: {out_path}")
        else:
            print(f"-> No valid meshes found for group {group}. Nothing to merge.")

    print("\nProcessing finished successfully.")


if __name__ == "__main__":
    config = SystemConfig()
    merge_meshes_by_group(config)