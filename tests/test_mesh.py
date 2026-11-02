import numpy as np
import pytest
import trimesh

from functions.utils.mesh import close_link


def _open_box():
    box = trimesh.creation.box()
    keep = box.face_normals[:, 2] < 0.5  # drop the top face (2 triangles)
    return box.vertices, box.faces[keep]


def _half_box_fragments(tmp_path):
    """Two overlapping convex halves of the unit box, saved like decompose-stage fragments."""
    paths = []
    for i, x in enumerate((-0.2, 0.2)):
        half = trimesh.creation.box(extents=(0.6, 1.0, 1.0))
        half.apply_translation((x, 0.0, 0.0))
        paths.append(str(tmp_path / f"fragment_{i + 1}.ply"))
        half.export(paths[-1])
    return paths


def test_close_link_closes_holes():
    out = close_link(*_open_box(), {"selfintersection": False}, None)
    assert out.is_watertight and abs(out.volume - 1.0) < 1e-6


def test_close_link_falls_back_to_fragment_union(tmp_path):
    out = close_link(*_open_box(), {"maxholesize": 1}, _half_box_fragments(tmp_path))  # hole too large to close
    assert out.is_watertight and abs(out.volume - 1.0) < 1e-6


def test_close_link_without_fragments_raises():
    with pytest.raises(RuntimeError, match="Re-run the segment stage"):
        close_link(*_open_box(), {"maxholesize": 1}, None)
