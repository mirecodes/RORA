from functions.gui.models import (PartAssignment, cycle_state, group_fragments, group_pairs,
                                  valid_vectors)


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


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
