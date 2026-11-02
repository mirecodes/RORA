import json
import os
import tempfile

import yaml

from functions.gui.study import KINDS, Recorder, load_study, save_trial, trial_record


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        (json.dump if path.endswith(".json") else yaml.safe_dump)(doc, f)


def _repo(root):
    _write(os.path.join(root, "cfgs/dev/set.yml"),
           {"defaults": {"extension": "ply", "profile": "partnet_object"},
            "objects": {"cat1": {"fan": {"parts": 2, "object_profile": None}, "box": {"parts": 5}}}})
    _write(os.path.join(root, "working/fan/attributes/states.json"), {"refine": {"x": 1}, "segment": {"x": 1}})
    _write(os.path.join(root, "working/box/attributes/states.json"), {"refine": {"x": 1}})


def test_load_study_valid():
    with tempfile.TemporaryDirectory() as root:
        _repo(root)
        path = os.path.join(root, "cfgs/study/P01.yml")
        _write(path, {"participant": "P01", "objects_from": "cfgs/dev/set.yml",
                      "trials": [{"object": "fan", "condition": "A"}, {"object": "fan", "condition": "B"}]})
        s = load_study(path, root=root)
        assert s["participant"] == "P01" and s["study_file"] == "cfgs/study/P01.yml"
        assert [(t["index"], t["object"], t["condition"]) for t in s["trials"]] == [(1, "fan", "A"), (2, "fan", "B")]
        assert s["trials"][0]["entry"] == {"extension": "ply", "profile": "partnet_object", "parts": 2,
                                           "object_profile": None}


def test_load_study_lists_every_bad_trial():
    with tempfile.TemporaryDirectory() as root:
        _repo(root)
        path = os.path.join(root, "P02.yml")
        _write(path, {"participant": "P02", "objects_from": "cfgs/dev/set.yml",
                      "trials": [{"object": "fan", "condition": "A"}, {"object": "box", "condition": "B"},
                                 {"object": "ghost", "condition": "A"}, {"object": "fan", "condition": "C"}]})
        try:
            load_study(path, root=root)
        except ValueError as e:
            msg = str(e)
        else:
            raise AssertionError("expected ValueError")
        assert "trial 1" not in msg
        assert "trial 2: box has no segment" in msg
        assert "trial 3: object 'ghost'" in msg
        assert "trial 4: condition 'C'" in msg


def test_recorder_counts_and_auto_repeat():
    t = [0.0]
    rec = Recorder(clock=lambda: t[0])
    rec.log("gui", "before start")                  # ignored: not active
    rec.start()
    t[0] = 1.0
    rec.log("key", "W")
    t[0] = 1.5
    rec.log("key", "W", repeat=True)                # held key: logged, not counted
    rec.log("axis", "left")
    t[0] = 4.25
    assert rec.stop() == 4.25 and not rec.active
    rec.log("gui", "after stop")                    # ignored
    assert rec.counts == {"gui": 0, "axis": 1, "gizmo": 0, "view": 0, "key": 1}
    assert rec.events == [{"t": 1.0, "kind": "key", "detail": "W", "repeat": False},
                          {"t": 1.5, "kind": "key", "detail": "W", "repeat": True},
                          {"t": 1.5, "kind": "axis", "detail": "left"}]
    rec.start()                                     # a new trial starts clean
    assert rec.events == [] and all(v == 0 for v in rec.counts.values()) and set(rec.counts) == set(KINDS)


def test_save_trial_writes_only_study_folders_and_session():
    with tempfile.TemporaryDirectory() as root:
        study = {"participant": "P01", "study_file": "cfgs/study/P01.yml",
                 "trials": [{"index": 1, "object": "fan", "condition": "A"},
                            {"index": 2, "object": "fan", "condition": "B"},
                            {"index": 3, "object": "box", "condition": "A"}]}
        t = [0.0]
        rec = Recorder(clock=lambda: t[0])
        records = []
        # the run stops after trial 2 of 3: session.yml must already hold trials 1-2
        for trial, dur, kind in zip(study["trials"][:2], (10.0, 4.0), ("gizmo", "axis")):
            t[0] = 0.0
            rec.start()
            rec.log(kind)
            t[0] = dur
            rec.stop()
            joint = {"parent": 1, "child": 2, "type": "Revolute",
                     "axis": {"origin": [0.0, 0.0, 0.0], "n": [0.0, 0.0, 1.0]}}
            record = trial_record(study, trial, "2026-11-03T14:00:00", rec, [joint],
                                  [{"parent": 2, "child": 1}] if trial["condition"] == "A" else None)
            sugg = [{"pair": [1, 2], "origin": [0.0, 0.0, 0.0], "n": [0.0, 0.0, 1.0], "state": "Revolute"}]
            save_trial(study, "20261103_140000", "2026-11-03T14:00:00", records, record,
                       sugg if trial["condition"] == "B" else None, root=root)
        files = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)
        assert files == ["export/study/20261103_140000/fan/01_A.yml", "export/study/20261103_140000/fan/02_B.yml",
                         "export/study/20261103_140000/session.yml",
                         "working/study/20261103_140000/fan/02_B_suggestions.json"]
        with open(os.path.join(root, "export/study/20261103_140000/session.yml"), encoding="utf-8") as f:
            session = yaml.safe_load(f)
        assert [r["record"] for r in session["trials"]] == ["fan/01_A.yml", "fan/02_B.yml"]
        assert session["totals"]["A"] == {"trials": 1, "duration_s": 10.0,
                                          "counts": {"gui": 0, "axis": 0, "gizmo": 1, "view": 0, "key": 0}}
        assert session["totals"]["B"]["trials"] == 1 and session["totals"]["B"]["counts"]["axis"] == 1
        with open(os.path.join(root, "export/study/20261103_140000/fan/01_A.yml"), encoding="utf-8") as f:
            a = yaml.safe_load(f)
        assert a["manual_pairs"] == [{"parent": 2, "child": 1}] and a["duration_s"] == 10.0
        assert a["events"] == [{"t": 0.0, "kind": "gizmo", "detail": ""}]


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
