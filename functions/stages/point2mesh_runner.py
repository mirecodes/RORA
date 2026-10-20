"""Run the unmodified point2mesh submodule with runtime fixes, so the submodule stays pristine.

Runs inside point2mesh's own venv (no RORA imports):
    submodules/point2mesh/.venv/bin/python point2mesh_runner.py <point2mesh main.py args...>
"""
import os
import runpy
import sys
import types

import numpy as np
import torch

P2M_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "submodules", "point2mesh")
P2M_DIR = os.path.abspath(P2M_DIR)
sys.path.insert(0, P2M_DIR)

import models.layers.mesh as p2m_mesh  # noqa: E402


# Fix 1: numpy>=1.24 raises on np.array(<ragged lists>) used in Mesh.build_gemm.
# Restore the old behaviour (object array) for mesh.py only.
def _array(obj, *args, **kwargs):
    try:
        return np.array(obj, *args, **kwargs)
    except ValueError:
        return np.array(obj, dtype=object)


class _NumpyShim(types.ModuleType):
    array = staticmethod(_array)

    def __getattr__(self, name):  # everything else (incl. lazy submodules like np.ma) -> real numpy
        return getattr(np, name)


p2m_mesh.np = _NumpyShim("numpy")


# Fix 2: Mesh.build_gfmm assumes every face has exactly 3 neighbours (watertight manifold).
# Boundary edges -> use the face itself, non-manifold edges -> keep the first neighbour.
def _build_gfmm(self):
    edge_faces = self.build_ef()
    faces = self.faces.cpu().numpy() if isinstance(self.faces, torch.Tensor) else self.faces
    gfmm = []
    for face_id, face in enumerate(faces):
        neighbors = [face_id]
        for i in range(3):
            edge = tuple(sorted([face[i], face[(i + 1) % 3]]))
            nb = list(set(edge_faces[edge]) - {face_id})
            neighbors.append(nb[0] if nb else face_id)
        gfmm.append(neighbors)
    return torch.Tensor(gfmm).long().to(self.device)


p2m_mesh.Mesh.build_gfmm = _build_gfmm


if __name__ == "__main__":
    os.chdir(P2M_DIR)
    sys.argv = [os.path.join(P2M_DIR, "main.py")] + sys.argv[1:]
    runpy.run_path(sys.argv[0], run_name="__main__")
