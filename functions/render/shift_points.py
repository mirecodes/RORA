import os

import numpy as np
from plyfile import PlyData, PlyElement

def translate_ply(input_path: str, output_path: str, offset: tuple):
    """
    Shift all vertices of a .ply by the given offset and print
    the mean position before/after.

    Args:
        input_path (str): source .ply path
        output_path (str): output .ply path
        offset (tuple): (x_offset, y_offset, z_offset)
    """
    try:
        # 1. Read .ply
        print(f"Reading '{input_path}'...")
        plydata = PlyData.read(input_path)

        # 2. Check 'vertex' element
        if 'vertex' not in plydata:
            print("Error: no 'vertex' element in file.")
            return

        vertices = plydata['vertex']

        # 3. Mean position before shift
        avg_x_before = np.mean(vertices['x'])
        avg_y_before = np.mean(vertices['y'])
        avg_z_before = np.mean(vertices['z'])
        print("-" * 30)
        print(f"Mean position before shift:")
        print(f"  Avg X: {avg_x_before:.6f}")
        print(f"  Avg Y: {avg_y_before:.6f}")
        print(f"  Avg Z: {avg_z_before:.6f}")
        print("-" * 30)

        # 4. Offset
        x_offset, y_offset, z_offset = offset
        print(f"Offset: (x: {x_offset}, y: {y_offset}, z: {z_offset})")

        # 5. Shift vertices
        vertices['x'] -= x_offset
        vertices['y'] -= y_offset
        vertices['z'] -= z_offset
        # vertices['x'] -= avg_x_before
        # vertices['y'] -= avg_y_before
        # vertices['z'] -= avg_z_before
        print("All vertices shifted.")

        # 6. Mean position after shift
        avg_x_after = np.mean(vertices['x'])
        avg_y_after = np.mean(vertices['y'])
        avg_z_after = np.mean(vertices['z'])
        print("-" * 30)
        print(f"Mean position after shift:")
        print(f"  Avg X: {avg_x_after:.6f}")
        print(f"  Avg Y: {avg_y_after:.6f}")
        print(f"  Avg Z: {avg_z_after:.6f}")
        print("-" * 30)

        # 7. Write new .ply
        print(f"Saving to '{output_path}'...")
        plydata.write(output_path)

        print("Done.")

    except FileNotFoundError:
        print(f"Error: '{input_path}' not found.")
    except Exception as e:
        print(f"Error: {e}")


# --- Main ---
if __name__ == "__main__":

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # functions/

    # --- Edit here ---

    # 1. Source .ply path
    input_file = os.path.abspath(os.path.join(base_dir, "..", "export", "transfer", "spray_gaussian_6.ply"))

    # 2. Output .ply path
    output_file = os.path.abspath(os.path.join(base_dir, "..", "export", "shifted_meshes", "shifted_spray_gaussian_6.ply"))

    # 3. Offset vector
    offset_vector = (0.639987, 1.448243, 1.526706)

    # -------------------------

    # Run
    translate_ply(input_file, output_file, offset_vector)