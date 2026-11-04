import tempfile
import xml.etree.ElementTree as ET

import numpy as np
import trimesh

from functions.gui.models import (ManualJoints, PartAssignment, cycle_state, group_fragments, group_pairs,
                                  valid_vectors)
from functions.utils.urdf import generate_urdf, joints_from_bicons


def test_part_assignment():
    m = PartAssignment(n_fragments=3, parts_num=2)
    assert m.owner == [0, 1, 1, 1] and m.mode == 0
    assert not m.assign(2)              # view mode ignores clicks
    assert m.cycle_mode() == 1 and m.cycle_mode() == 2 and m.cycle_mode() == 0
    m.set_mode(2)
    assert m.assign(2) and m.owner[2] == 2
    assert m.counts() == {1: 2, 2: 1}
    assert m.undo(2) and m.owner[2] == 1
    m.set_mode(9)
    assert m.mode == 2
    assert group_fragments(["f1", "f2", "f3"], [0, 1, 2, 1], 2) == [[], ["f1", "f3"], ["f2"]]


def test_group_pairs_skips_zero_pair_and_keeps_order():
    bicons = [{"a": {"src": 2, "dst": 1}}, {"a": {"src": 0, "dst": 0}}, {"a": {"src": 1, "dst": 2}},
              {"a": {"src": 3, "dst": 1}}]
    pairs = group_pairs(bicons)
    assert [k for k, _ in pairs] == [(1, 2), (1, 3)]
    assert len(pairs[0][1]) == 2
    assert group_pairs([{"a": {"src": 0, "dst": 0}}]) == []


def test_valid_vectors_skips_bad_normals_and_fills_center():
    good = {"n": [0, 0, 1]}
    bicon = {"center": [1.0, 2.0, 3.0],
             "vectors": [good, {"n": [float("nan"), 0, 0]}, {"n": [0, 0, 0]}, {"center": [0, 0, 0]}]}
    out = valid_vectors([bicon, {"vectors": None}])
    assert out == [(bicon, good)] and good["center"] == [1.0, 2.0, 3.0]


def test_cycle_state_orders_revolute_picks():
    counter = [0]
    a, b = {}, {"state": "Prismatic", "order": 4}
    assert cycle_state(a, counter) == "Revolute" and a["order"] == 1
    assert cycle_state(a, counter) == "Prismatic" and a["order"] == 1
    assert cycle_state(a, counter) == "None" and a["order"] is None
    assert cycle_state(b, counter) == "None" and b["order"] is None
    assert cycle_state(b, counter) == "Revolute" and b["order"] == 2


def test_manual_joints_flow():
    m = ManualJoints(parts_num=3)
    assert (m.parent, m.child) == (1, 2) and m.can_add()
    assert not m.confirm()                          # no triad yet
    assert m.new_joint() and not m.new_joint()      # one triad at a time
    assert [v["n"] for v in m.triad] == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    assert all(v["center"] == [0.0, 0.0, 0.0] for v in m.triad)
    assert not m.confirm()                          # no arrow picked
    cycle_state(m.triad[2], m.counter)
    m.triad[2]["center"] = [0.5, 0.0, 0.0]
    m.parent, m.child = 3, 1
    assert m.confirm() and m.triad is None and m.can_add()
    assert [(j["parent"], j["child"], len(j["triad"])) for j in m.confirmed] == [(3, 1, 3)]  # whole triad kept
    assert ManualJoints.describe(m.confirmed[0]) == "3 → 1 · Revolute Z"
    joints = joints_from_bicons(m.bicons())
    assert len(joints) == 1 and joints[0]["type"] == "Revolute"
    assert (joints[0]["parent"], joints[0]["child"]) == (1, 3)
    assert joints[0]["axis"]["n"] == [0.0, 0.0, 1.0] and joints[0]["axis"]["origin"] == [0.5, 0.0, 0.0]
    m.remove(0)
    assert m.confirmed == [] and m.bicons() == []


def test_manual_joints_refuses_same_part():
    m = ManualJoints(parts_num=2)
    m.child = 1
    assert not m.can_add() and not m.new_joint() and m.triad is None
    m.child = 2
    assert m.new_joint()
    cycle_state(m.triad[0], m.counter)
    m.child = 1
    assert not m.confirm() and m.triad is not None and m.confirmed == []


def test_manual_joints_edit_cancel_and_update():
    m = ManualJoints(parts_num=3)
    for parent, child, axis in ((1, 2, 2), (1, 3, 0)):
        m.parent, m.child = parent, child
        m.new_joint()
        cycle_state(m.triad[axis], m.counter)
        m.confirm()
    m.parent, m.child = 2, 3
    assert m.edit(0) and m.editing == 0 and (m.parent, m.child) == (1, 2)
    assert not m.edit(1) and not m.remove(1) and not m.can_add()   # one joint at a time
    cycle_state(m.triad[2], m.counter)                               # Revolute -> Prismatic
    m.triad[2]["center"] = [9.0, 9.0, 9.0]
    m.cancel()
    assert m.triad is None and m.editing is None
    assert ManualJoints.describe(m.confirmed[0]) == "1 → 2 · Revolute Z"     # cancel keeps the original
    assert m.confirmed[0]["triad"][2]["center"] == [0.0, 0.0, 0.0]
    assert m.edit(0)
    cycle_state(m.triad[2], m.counter)
    m.child = 3
    assert m.confirm() and m.editing is None
    assert [ManualJoints.describe(j) for j in m.confirmed] == ["1 → 3 · Prismatic Z", "1 → 3 · Revolute X"]
    assert m.remove(0) and [ManualJoints.describe(j) for j in m.confirmed] == ["1 → 3 · Revolute X"]


def test_manual_joints_two_arrows_merge_like_suggestions():
    m = ManualJoints(parts_num=2)
    m.new_joint()
    cycle_state(m.triad[0], m.counter)
    cycle_state(m.triad[1], m.counter)
    assert m.confirm()
    assert [j["type"] for j in joints_from_bicons(m.bicons())] == ["Spherical"]


def test_generate_urdf_joint_limits():
    parts = {0: trimesh.creation.box(), 1: trimesh.creation.box(), 2: trimesh.creation.box()}
    parts[2].apply_translation([3, 0, 0])           # union bbox 4 x 1 x 1
    axis = {"origin": [0, 0, 0], "n": [0, 0, 1]}
    joints = [{"parent": 0, "child": 1, "type": "revolute", "axis": axis},
              {"parent": 1, "child": 2, "type": "prismatic", "axis": axis}]
    with tempfile.TemporaryDirectory() as out_dir:
        path = generate_urdf(parts, joints, out_dir=out_dir, transform_matrix=np.diag([2.0, 2.0, 2.0, 1.0]),
                             suggestions=[{"pair": (0, 1), "origin": [0, 0, 0], "n": [1, 0, 0]}])
        limits = {j.get("name"): j.find("limit") for j in ET.parse(path).getroot().findall("joint")}
    for name, expected in (("joint_0_1", 2 * np.pi), ("suggest_0_1_0", 2 * np.pi),
                           ("joint_1_2", 2 * np.sqrt(18))):      # prismatic: diagonal after the transform
        assert np.isclose(float(limits[name].get("upper")), expected)
        assert np.isclose(float(limits[name].get("lower")), -expected)


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
