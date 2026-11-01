# Articulation User Study Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `--study <file>` mode of the pipeline GUI that runs articulation trials (condition A: manual
triad joints, condition B: suggested vectors) in a listed order and records time, categorized clicks,
key presses, events, and final joints per trial.

**Architecture:** Study logic that needs no Qt (study file loading, `Recorder`, trial records, session
summary, output paths) lives in `functions/gui/study.py`; `ManualJoints` (pure triad state) lives in
`models.py`. The window runs `study.run_trial()` on its own worker thread through the existing
`UiBridge`, starts the recorder when the trial's scene mounts and stops it on Done. Viewport clicks are
reported by the viewport (`on_input` callback); panel clicks and keys by an app-level `InputFilter`.

**Tech Stack:** Python 3.12 (`.venv`), PySide6, vedo/VTK, PyYAML, numpy.

**Spec:** `docs/superpowers/specs/2026-10-31-user-study-design.md`

## Global Constraints

- All UI text, identifiers, comments, docstrings, log messages, and docs are in English (`CLAUDE.md`).
- Run tests from the repo root with `.venv/bin/python -m tests.<module>` (plain `test_*` functions with a
  `__main__` runner, no pytest).
- `functions/gui/study.py` must import no Qt/VTK at module level; heavy imports go inside `run_trial` /
  `trial_cfgs`.
- Study mode writes only to `export/study/<YYYYMMDD_HHMMSS>/` and `working/study/<YYYYMMDD_HHMMSS>/`.
  `states.json` is opened with `JsonHandler(..., auto_save=False)` (read-only). No `timing.yml`.
- Count categories are exactly `gui`, `axis`, `gizmo`, `view`, `key`. Auto-repeated keys are logged with
  `repeat: true` and not counted.
- Conditions are exactly `A` and `B`.
- Do not commit: the working tree holds unrelated uncommitted user changes (including `articulate.py`).

## Review Focus

1. A click on a panel label (ignored, so Qt re-sends it to each parent) must count as one `gui` click,
   and a viewport click must not be counted by the app filter at all. Test in Task 6.
2. Holding a movement key down (auto-repeat) must count as one key press. Test in Task 3.
3. **+ New joint** with parent == child, or **Confirm joint** with no Revolute/Prismatic arrow, must be
   refused without changing state. Test in Task 2.
4. A study file with an unknown object, an invalid condition, or an object without `refine`/`segment`
   results must fail before the window opens, listing every bad trial. Test in Task 3.
5. A run closed after trial 2 of 4 must leave a valid `session.yml` with trials 1–2 and correct totals.
   Test in Task 3.

## File Map

| File | Responsibility |
|---|---|
| `functions/pipeline/articulate.py` | `load_segmented`, `suggest_bicons` extracted; stage uses them. |
| `functions/gui/models.py` | `ManualJoints`. |
| `functions/gui/study.py` (new) | `load_study`, `Recorder`, `trial_record`, `session_doc`, `save_trial`, `trial_cfgs`, `run_trial`. |
| `functions/gui/scenes.py` | `on_pick` returns `bool`; `ManualJointScene`; `manual` smoke target. |
| `functions/gui/viewport.py` | `on_input` callback for viewport presses. |
| `functions/gui/window.py` | `InputFilter`; study mode (header, trial thread, records). |
| `functions/gui/app.py` | `--study FILE`. |
| `cfgs/study/example.yml` (new) | Example study file. |
| `tests/test_models.py`, `tests/test_study.py` (new), `tests/test_input_filter.py` (new) | Tests. |

---

### Task 1: Extract `load_segmented` and `suggest_bicons`

**Files:**
- Modify: `functions/pipeline/articulate.py` (`stage_articulate`)

**Interfaces:**
- Produces: `load_segmented(states) -> (verts, faces, vert_label, parts_num)`;
  `suggest_bicons(art_cfgs: dict, verts, faces, vert_label, parts_num: int, debug: bool = False,
  step=lambda key: None) -> list[dict]`.

- [ ] **Step 1: Add the helpers above the stage section**

```python
def load_segmented(states):
    """(verts, faces, vert_label, parts_num): the refined mesh with the segment stage's vertex labels."""
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(states.refine.dirs.mesh)
    ms.set_current_mesh(0)
    current_mesh = ms.current_mesh()
    verts = current_mesh.vertex_matrix()
    faces = current_mesh.face_matrix().astype(np.int64)
    vert_label = np.load(states.segment.dirs.vert_label).astype(int)
    parts_num = int(states.segment.parts_num)
    if len(vert_label) != len(verts):
        raise RuntimeError(f"[error]: vert_label ({len(vert_label)}) does not match refined mesh ({len(verts)} verts). "
                           "Re-run the segment stage.")
    return verts, faces, vert_label, parts_num


def suggest_bicons(art_cfgs: dict, verts, faces, vert_label, parts_num: int, debug: bool = False,
                   step=lambda key: None) -> List[dict]:
    """Automatic joint suggestion: axis estimation (unicons) → bidirectional fusion (bicons) → vector
    candidates on each bicon. `step(key)` reports the 'unicons' and 'fusion' sub-steps."""
    adj = adjacency(faces, len(verts))
    step("unicons")
    print("[info] Estimating unidirectional connections (unicons)...")
    unicons = compute_unicons(verts, faces, parts_num, adj, vert_label, visualize_results=debug,
                              **art_cfgs["axis_estimation"])

    step("fusion")
    print("[info] Fusing unicons into bidirectional connections (bicons)...")
    diag = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
    bicons = fuse_connections(unicons, scale=diag, **art_cfgs["fusion"])
    if debug:
        show_bicons(verts, faces, bicons)
    if art_cfgs["allow_unpaired_unicon"]:
        append_unpaired_unicons(unicons, bicons, verts)
    print(f"[info]: len bicons {len(bicons)}")

    prepare_vectors_for_bicons(bicons)
    augment_vectors_for_pairs_with_map(bicons, min_count=art_cfgs["vector_augment_min_count"])  # optional
    return bicons
```

- [ ] **Step 2: Replace the stage's load/estimate block with the helpers**

```python
    print("[info] Loading states, base mesh and vertex labels...")
    states = JsonHandler(cfgs.json_states_dir, auto_save=True)
    verts, faces, vert_label, parts_num = load_segmented(states)
    bicons = suggest_bicons(artCfgs, verts, faces, vert_label, parts_num, debug=cfgs.debug_mode, step=ui().step)
```

- [ ] **Step 3: Verify on a real object (headless, NullBridge)**

Run: `.venv/bin/python -c "from json_handler import JsonHandler; from functions.pipeline.articulate import load_segmented, suggest_bicons; from functions.utils.config import load_params; v,f,l,n = load_segmented(JsonHandler('working/fan/attributes/states.json', auto_save=False)); b = suggest_bicons(load_params()['articulate'], v, f, l, n); print(n, len(b), sum(len(x.get('vectors') or []) for x in b))"`
Expected: prints `2 <bicons> <vectors>` with bicons ≥ 1; `git diff --stat working/` stays empty.

### Task 2: `ManualJoints`

**Files:**
- Modify: `functions/gui/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `cycle_state` (models.py), `joints_from_bicons` (utils/urdf.py) in tests.
- Produces: `ManualJoints(parts_num)` with `parent`, `child`, `triad: list[dict] | None`, `counter`,
  `confirmed: list[{"parent","child","vectors"}]`, `can_add()`, `new_joint() -> bool`, `picked()`,
  `can_confirm()`, `confirm() -> bool`, `remove(i)`, `bicons() -> list[dict]`, `describe(joint) -> str`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_models.py`, import `ManualJoints` and
  `from functions.utils.urdf import joints_from_bicons`)

```python
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
    assert [(j["parent"], j["child"], len(j["vectors"])) for j in m.confirmed] == [(3, 1, 1)]
    assert ManualJoints.describe(m.confirmed[0]) == "Parent 3 → Child 1 · Revolute (Z)"
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


def test_manual_joints_two_arrows_merge_like_suggestions():
    m = ManualJoints(parts_num=2)
    m.new_joint()
    cycle_state(m.triad[0], m.counter)
    cycle_state(m.triad[1], m.counter)
    assert m.confirm()
    assert [j["type"] for j in joints_from_bicons(m.bicons())] == ["Spherical"]
```

- [ ] **Step 2: Run, expect ImportError** — `.venv/bin/python -m tests.test_models`

- [ ] **Step 3: Implement** (append to `functions/gui/models.py`)

```python
JOINT_STATES = ("Revolute", "Prismatic")


class ManualJoints:
    """User study condition A: joints authored one at a time from an X/Y/Z triad at the world origin.
    Triad arrows cycle state like suggested vectors; confirm() stores the picked arrows with the chosen
    parent/child, and bicons() hands the confirmed joints to joints_from_bicons."""

    def __init__(self, parts_num: int):
        self.parts_num = parts_num
        self.parent, self.child = 1, min(2, parts_num)
        self.triad: list[dict] | None = None
        self.counter = [0]
        self.confirmed: list[dict] = []   # {"parent", "child", "vectors"}

    def can_add(self) -> bool:
        return self.triad is None and self.parent != self.child

    def new_joint(self) -> bool:
        if not self.can_add():
            return False
        self.triad = [{"center": [0.0, 0.0, 0.0], "n": [float(x) for x in e], "state": "None", "axis": a}
                      for a, e in zip("XYZ", np.eye(3))]
        self.counter = [0]
        return True

    def picked(self) -> list[dict]:
        return [v for v in self.triad or [] if v.get("state") in JOINT_STATES]

    def can_confirm(self) -> bool:
        return bool(self.picked()) and self.parent != self.child

    def confirm(self) -> bool:
        if not self.can_confirm():
            return False
        self.confirmed.append({"parent": self.parent, "child": self.child,
                               "vectors": [dict(v) for v in self.picked()]})
        self.triad = None
        return True

    def remove(self, i: int) -> None:
        del self.confirmed[i]

    def bicons(self) -> list[dict]:
        return [{"a": {"src": j["parent"], "dst": j["child"]}, "vectors": j["vectors"]} for j in self.confirmed]

    @staticmethod
    def describe(joint: dict) -> str:
        arrows = ", ".join(f"{v['state']} ({v['axis']})" for v in joint["vectors"])
        return f"Parent {joint['parent']} → Child {joint['child']} · {arrows}"
```

- [ ] **Step 4: Run, expect `ok`** — `.venv/bin/python -m tests.test_models`

### Task 3: `study.py` — study file, recorder, records, session

**Files:**
- Create: `functions/gui/study.py`, `tests/test_study.py`, `cfgs/study/example.yml`

**Interfaces:**
- Consumes: `read_states(path)` (gui/runner.py), `functions.utils.config` loaders.
- Produces: `ROOT`, `CONDITIONS`, `KINDS`; `load_study(path, root=ROOT) -> {"participant",
  "study_file", "trials": [{"index", "object", "condition", "entry"}]}`; `Recorder(clock)` with
  `start()`, `stop() -> float`, `log(kind, detail="", repeat=False)`, `active`, `counts`, `events`,
  `duration`; `trial_record(study, trial, started, recorder, joints, manual_pairs=None) -> dict`;
  `session_doc(study, started, records) -> dict`; `save_trial(study, stamp, started, records, record,
  suggestions=None, root=ROOT) -> str` (appends to `records`); `trial_cfgs(trial)`;
  `run_trial(trial) -> (joints, manual_pairs | None, suggestions | None)`.

- [ ] **Step 1: Write the failing tests** (`tests/test_study.py`)

```python
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
        rec, t = Recorder(clock=lambda: t[0]), [0.0]
        records = []
        for trial, dur, kind in zip(study["trials"][:2], (10.0, 4.0), ("gizmo", "axis")):
            t[0] = 0.0
            rec.start()
            rec.log(kind)
            t[0] = dur
            rec.stop()
            joint = {"parent": 1, "child": 2, "type": "Revolute", "axis": {"origin": [0.0, 0.0, 0.0], "n": [0.0, 0.0, 1.0]}}
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
```

- [ ] **Step 2: Run, expect ImportError** — `.venv/bin/python -m tests.test_study`

- [ ] **Step 3: Implement `functions/gui/study.py`**

```python
"""User study mode (articulation): study file, input recorder, trial records, and the session summary.
Qt-free: the window feeds the recorder from Qt/VTK input and runs run_trial() on a worker thread.
Outputs go only to export/study/<stamp>/ and working/study/<stamp>/; states.json is only read."""
import json
import os
import time

import yaml

from functions.gui.runner import read_states
from functions.utils.config import (CFG_DIR, _merge, apply_object_profile, load_cfg, load_params,
                                    object_profile_params)

ROOT = os.path.dirname(CFG_DIR)
CONDITIONS = ("A", "B")              # A: manual triad joints, B: suggested vectors
KINDS = ("gui", "axis", "gizmo", "view", "key")
NEEDS = ("refine", "segment")        # states.json sections a trial reads


def _load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_study(path: str, root: str = ROOT) -> dict:
    """Validated study file: {"participant", "study_file", "trials": [{"index", "object", "condition",
    "entry"}]}, `entry` being the object's manifest row with the manifest defaults applied.
    Raises ValueError listing every problem at once."""
    doc = _load_yaml(path)
    if not doc.get("participant") or not doc.get("objects_from"):
        raise ValueError(f"{path}: `participant` and `objects_from` are required")
    manifest = _load_yaml(os.path.join(root, doc["objects_from"]))
    defaults = manifest.get("defaults") or {}
    objects = {name: {**defaults, **(e or {})}
               for objs in (manifest.get("objects") or {}).values() for name, e in (objs or {}).items()}
    trials, errors = [], []
    for i, t in enumerate(doc.get("trials") or [], start=1):
        name, cond = t.get("object"), t.get("condition")
        if name not in objects:
            errors.append(f"trial {i}: object '{name}' is not in {doc['objects_from']}")
            continue
        if cond not in CONDITIONS:
            errors.append(f"trial {i}: condition '{cond}' is not one of {', '.join(CONDITIONS)}")
        states = read_states(os.path.join(root, "working", name, "attributes", "states.json"))
        missing = [s for s in NEEDS if not states.get(s)]
        if missing:
            errors.append(f"trial {i}: {name} has no {', '.join(missing)} results in working/{name}/attributes/states.json")
        trials.append({"index": i, "object": name, "condition": cond, "entry": objects[name]})
    if not doc.get("trials"):
        errors.append("no trials listed")
    if errors:
        raise ValueError(f"{path}:\n  " + "\n  ".join(errors))
    return {"participant": str(doc["participant"]), "study_file": os.path.relpath(os.path.abspath(path), root),
            "trials": trials}


class Recorder:
    """Clicks and keys of one trial, by category (KINDS). log() is a no-op outside start()..stop().
    Auto-repeated keys stay in the event stream (repeat: true) but are not counted."""

    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.active = False
        self._reset()

    def _reset(self) -> None:
        self.events, self.counts, self.duration = [], dict.fromkeys(KINDS, 0), 0.0

    def start(self) -> None:
        self._reset()
        self._t0, self.active = self.clock(), True

    def stop(self) -> float:
        if self.active:
            self.duration, self.active = self.clock() - self._t0, False
        return self.duration

    def log(self, kind: str, detail: str = "", repeat: bool = False) -> None:
        if not self.active:
            return
        event = {"t": round(self.clock() - self._t0, 3), "kind": kind, "detail": str(detail)}
        if kind == "key":
            event["repeat"] = bool(repeat)
        self.events.append(event)
        if not repeat:
            self.counts[kind] += 1


def _stem(trial_index: int, condition: str) -> str:
    return f"{trial_index:02d}_{condition}"


def trial_record(study: dict, trial: dict, started: str, recorder: Recorder, joints: list,
                 manual_pairs: list | None = None) -> dict:
    record = {"participant": study["participant"], "trial": trial["index"], "object": trial["object"],
              "condition": trial["condition"], "started": started, "duration_s": round(recorder.duration, 3),
              "counts": dict(recorder.counts), "joints": joints}
    if manual_pairs is not None:
        record["manual_pairs"] = manual_pairs
    record["events"] = list(recorder.events)
    return record


def session_doc(study: dict, started: str, records: list) -> dict:
    totals = {c: {"trials": 0, "duration_s": 0.0, "counts": dict.fromkeys(KINDS, 0)} for c in CONDITIONS}
    rows = []
    for r in records:
        rows.append({"trial": r["trial"], "object": r["object"], "condition": r["condition"],
                     "duration_s": r["duration_s"], "counts": r["counts"], "joints": len(r["joints"]),
                     "record": f"{r['object']}/{_stem(r['trial'], r['condition'])}.yml"})
        t = totals[r["condition"]]
        t["trials"] += 1
        t["duration_s"] = round(t["duration_s"] + r["duration_s"], 3)
        for k in KINDS:
            t["counts"][k] += r["counts"][k]
    return {"participant": study["participant"], "study_file": study["study_file"], "started": started,
            "trials": rows, "totals": totals}


def _dump_yaml(doc: dict, path: str) -> None:
    """Temp file + os.replace, so an interrupted run never leaves a partial yml."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = yaml.safe_dump(doc, sort_keys=False, default_flow_style=None, allow_unicode=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def save_trial(study: dict, stamp: str, started: str, records: list, record: dict,
               suggestions: list | None = None, root: str = ROOT) -> str:
    """Write the trial record (and B's suggestions), append it to `records`, rewrite session.yml.
    Returns the record path."""
    export_dir = os.path.join(root, "export", "study", stamp)
    stem = _stem(record["trial"], record["condition"])
    path = os.path.join(export_dir, record["object"], f"{stem}.yml")
    _dump_yaml(record, path)
    if suggestions is not None:
        out = os.path.join(root, "working", "study", stamp, record["object"], f"{stem}_suggestions.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(suggestions, f, indent=2)
    records.append(record)
    _dump_yaml(session_doc(study, started, records), os.path.join(export_dir, "session.yml"))
    return path


def trial_cfgs(trial: dict):
    """SystemConfigs for the trial's object: manifest row + its object profile (as scripts/dev/run_set.py
    sets up object_cfg.yml), without touching any cfg file."""
    from functions.pipeline.interface import SystemConfigs
    e = trial["entry"]
    obj = load_cfg("object_cfg")
    obj.update(object_name=trial["object"], extension=e["extension"], profile=e["profile"],
               parts={"num": e["parts"]})
    obj = apply_object_profile(obj, e.get("object_profile"))
    params = load_params(profile=obj.get("profile"), object_profile="")
    if obj["object_profile"]:
        params = _merge(params, object_profile_params(obj["object_profile"]))
    return SystemConfigs(obj=obj, params=params)


def run_trial(trial: dict):
    """Worker thread: show the condition's scene on the segmented mesh and return
    (joints, manual_pairs or None, suggestions or None). The window times the scene."""
    from json_handler import JsonHandler

    from functions.gui.bridge import ui
    from functions.gui.scenes import JointSelectScene, ManualJointScene
    from functions.pipeline.articulate import load_segmented, suggest_bicons
    from functions.utils.urdf import joints_from_bicons, suggestions_from_bicons
    from functions.visualize.style import set_vector_scale

    cfgs = trial_cfgs(trial)
    set_vector_scale(cfgs.params.get("visualization", {}).get("vector_scale"))
    verts, faces, vert_label, parts_num = load_segmented(JsonHandler(cfgs.json_states_dir, auto_save=False))
    if trial["condition"] == "A":
        result = ui().interact(ManualJointScene(verts, faces, vert_label, parts_num))
        return joints_from_bicons(result["bicons"]), result["manual_pairs"], None
    bicons = suggest_bicons(cfgs.params["articulate"], verts, faces, vert_label, parts_num)
    ui().interact(JointSelectScene(bicons, verts, faces, vert_label))
    suggestions = [{"pair": list(s["pair"]), "origin": s["origin"].tolist(), "n": s["n"].tolist(), "state": s["state"]}
                   for s in suggestions_from_bicons(bicons)]
    return joints_from_bicons(bicons), None, suggestions
```

- [ ] **Step 4: Add `cfgs/study/example.yml`**

```yaml
# User study: run with `.venv/bin/python -m functions.gui.app --study cfgs/study/example.yml`.
# Trials run in the listed order. condition A = manual triad joints, B = suggested vectors.
# Objects (parts, profile, object_profile) come from `objects_from`; each needs refine + segment results.
participant: P00
objects_from: cfgs/dev/batch_set_cfg.yml
trials:
  - {object: fan, condition: A}
  - {object: fan, condition: B}
```

- [ ] **Step 5: Run, expect `ok`** — `.venv/bin/python -m tests.test_study`

### Task 4: Scenes — `on_pick` returns bool, `ManualJointScene`

**Files:**
- Modify: `functions/gui/scenes.py`

**Interfaces:**
- Consumes: `ManualJoints` (Task 2), `VectorGroupTarget`, `cycle_state`, `state_arrow`, `label_colors`,
  `arrow_params`.
- Produces: `Scene.on_pick(actor, button) -> bool` (True = a joint arrow / fragment was changed);
  `ManualJointScene(verts, faces, vert_label, parts_num)`; `result() -> {"bicons", "manual_pairs"}`.

- [ ] **Step 1: `on_pick` returns bool** — `Scene.on_pick` returns `False`; `PartSelectScene.on_pick`
  returns `False` for a miss and `changed` otherwise; `JointSelectScene.on_pick` returns `False` for a
  miss/right click and `True` after cycling.

- [ ] **Step 2: Add `ManualJointScene` after `JointSelectScene`**

```python
class ManualJointScene(Scene):
    title = "Articulate · Manual joints"
    hint = "Pick parent and child, add a joint, move the triad, then click arrows: None → Revolute → Prismatic."
    controls = [("Click arrow", "cycle type")] + KEY_HINTS + [("G", "toggle gizmo"), ("R", "reset view"),
                                                             ("Enter", "confirm joint")]
    turn_deg = 1.5

    def __init__(self, verts, faces, vert_label, parts_num: int):
        super().__init__()
        self.verts, self.faces, self.vert_label = verts, faces, vert_label
        self.model = ManualJoints(parts_num)
        self.size = arrow_params(verts, scale=0.8)
        diag = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
        self.move_step = diag * 0.02 if np.isfinite(diag) and diag > 0 else 1.0
        self.arrows = {}        # vtkActor -> triad vector dict
        self.arrow_objs = []
        self.boxes = {}
        self.list_box = None

    def build(self) -> list:
        self.mesh = vedo.Mesh([self.verts, self.faces]).alpha(0.4).pickable(False)
        self._recolor()
        return [self.mesh, *self._make_arrows()]

    def _recolor(self) -> None:
        self.mesh.pointcolors = label_colors(self.vert_label, keep=(self.model.parent, self.model.child))

    def _make_arrows(self) -> list:
        """Pickable triad arrows plus the confirmed joints' arrows (faded, not pickable)."""
        self.arrows, self.arrow_objs = {}, []
        for v in self.model.triad or []:
            arrow = state_arrow(np.asarray(v["center"], dtype=float), normalize(v["n"]), v["state"], self.size)
            self.arrows[arrow.actor] = v
            self.arrow_objs.append(arrow)
        for joint in self.model.confirmed:
            for v in joint["vectors"]:
                arrow = state_arrow(np.asarray(v["center"], dtype=float), normalize(v["n"]), v["state"], self.size)
                self.arrow_objs.append(arrow.pickable(False).alpha(0.45))
        return self.arrow_objs

    def _redraw(self) -> None:
        if self.viewport is None:
            return
        if self.arrow_objs:
            self.viewport.plt.remove(*self.arrow_objs)
        self.viewport.plt.add(*self._make_arrows())

    def _changed(self) -> None:
        self._redraw()
        self._update_panel()
        self._render()

    def on_pick(self, actor, button: str) -> bool:
        v = self.arrows.get(actor)
        if v is None or button != "left":
            return False
        cycle_state(v, self.model.counter)
        self._changed()
        return True

    def on_enter(self) -> None:
        self._confirm()

    def _attach(self, target) -> None:
        self.target = target
        if self.viewport is not None:
            self.viewport.gizmo.attach(target)
        self._changed()

    def _new(self) -> None:
        if self.model.new_joint():
            self._attach(VectorGroupTarget(self.model.triad, on_change=lambda d: self._redraw()))

    def _confirm(self) -> None:
        if self.model.confirm():
            self._attach(None)

    def _remove(self, i: int) -> None:
        self.model.remove(i)
        self._changed()

    def _set_pair(self, *_) -> None:
        self.model.parent = self.boxes["parent"].currentData()
        self.model.child = self.boxes["child"].currentData()
        self._recolor()
        self._update_panel()
        self._render()

    def _done(self) -> None:
        if self.finish:
            self.finish()

    def widget(self) -> QWidget:
        w = QWidget()
        layout = _column(w)
        layout.addWidget(section("Part pair"))
        grid = QGridLayout()
        for row, key in enumerate(("parent", "child")):
            box = QComboBox()
            box.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keep keyboard focus in the viewport
            for p in range(1, self.model.parts_num + 1):
                box.addItem(f"Part {p}", p)
            box.setCurrentIndex(getattr(self.model, key) - 1)
            box.currentIndexChanged.connect(self._set_pair)
            self.boxes[key] = box
            grid.addWidget(QLabel(key.capitalize()), row, 0)
            grid.addWidget(box, row, 1)
        layout.addLayout(grid)
        row = QHBoxLayout()
        self.new_btn = button("+ New joint", self._new)
        self.confirm_btn = button("Confirm joint", self._confirm)
        row.addWidget(self.new_btn)
        row.addWidget(self.confirm_btn)
        layout.addLayout(row)
        layout.addWidget(section("Joints"))
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(4)
        layout.addLayout(self.list_box)
        footer = QHBoxLayout()
        footer.addStretch()
        self.primary = primary_button("Done ▸", self._done)
        footer.addWidget(self.primary)
        layout.addLayout(footer)
        self._update_panel()
        return w

    def _update_panel(self) -> None:
        if self.list_box is None:
            return
        self.new_btn.setEnabled(self.model.can_add())
        self.confirm_btn.setEnabled(self.model.can_confirm())
        while self.list_box.count():
            self.list_box.takeAt(0).widget().deleteLater()
        if not self.model.confirmed:
            self.list_box.addWidget(QLabel("No joints yet.", objectName="Muted"))
        for i, joint in enumerate(self.model.confirmed):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            text = QLabel(ManualJoints.describe(joint))
            text.setWordWrap(True)
            h.addWidget(text, 1)
            h.addWidget(button("✕", lambda i=i: self._remove(i)))
            self.list_box.addWidget(row)

    def on_theme(self) -> None:
        self._redraw()

    def result(self):
        return {"bicons": self.model.bicons(),
                "manual_pairs": [{"parent": j["parent"], "child": j["child"]} for j in self.model.confirmed]}
```

Imports: add `QComboBox` to the `PySide6.QtWidgets` import, `ManualJoints` to the models import.

- [ ] **Step 3: Add a `manual` smoke target in `__main__`**

```python
    elif kind == "manual":
        scene = ManualJointScene(verts, faces, np.where(verts[:, 0] < 0, 1, 2), 2)
```

- [ ] **Step 4: Smoke** — `.venv/bin/python -m functions.gui.scenes manual --smoke` and
  `... joints --smoke`. Expected: exits 0 without traceback.

### Task 5: Viewport input reporting

**Files:**
- Modify: `functions/gui/viewport.py` (`__init__`, `_left_press`, `_right_press`, `_pick`)

**Interfaces:**
- Produces: `Viewport.on_input: Callable[[str, str], None] | None` called with `("view", "cube" |
  "left" | "right" | "middle")`, `("gizmo", "left")`, `("axis", "left" | "right")`;
  `Viewport._pick(...) -> bool`.

- [ ] **Step 1: Implement**

```python
        self.on_input = None  # study mode: (kind, detail) for every viewport mouse press (Recorder.log)
        ...  # add ("MiddleButtonPressEvent", self._middle_press) to the observer list

    def _report(self, kind: str, detail: str) -> None:
        if self.on_input is not None:
            self.on_input(kind, detail)

    def _left_press(self, obj, ev):
        x, y = self.iren.GetEventPosition()
        if self.cube.on_press(x, y):
            self._report("view", "cube")
            self._swallow(ev)
            return
        if self.gizmo.on_press(x, y):
            self._report("gizmo", "left")
            self._swallow(ev)
            return
        self._report("axis" if self._pick(x, y, "left") else "view", "left")

    def _right_press(self, obj, ev):
        x, y = self.iren.GetEventPosition()
        if self.cube.contains(x, y):
            self._report("view", "cube")
            self._swallow(ev)
            return
        self._report("axis" if self._pick(x, y, "right") else "view", "right")

    def _middle_press(self, obj, ev):
        self._report("view", "middle")

    def _pick(self, x, y, button: str) -> bool:
        if self.scene is not None and self._picker.Pick(x, y, 0, self.renderer):
            return bool(self.scene.on_pick(self._picker.GetActor(), button))
        return False
```

- [ ] **Step 2: Smoke** — `.venv/bin/python -m functions.gui.viewport --smoke` exits 0.

### Task 6: Window study mode, `InputFilter`, `--study`

**Files:**
- Modify: `functions/gui/window.py`, `functions/gui/app.py`
- Test: `tests/test_input_filter.py`

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces: `InputFilter(recorder, viewport)`; `MainWindow(minimal=False, study=None)`.

- [ ] **Step 1: Write the failing test** (`tests/test_input_filter.py`)

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget  # noqa: E402

from functions.gui.study import Recorder  # noqa: E402
from functions.gui.window import InputFilter  # noqa: E402

app = QApplication.instance() or QApplication([])


def _mouse(ts, kind=QEvent.Type.MouseButtonPress):
    e = QMouseEvent(kind, QPointF(1, 1), QPointF(1, 1), Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    e.setTimestamp(ts)
    return e


def _key(ts, repeat=False):
    e = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_W, Qt.KeyboardModifier.NoModifier, "w", repeat)
    e.setTimestamp(ts)
    return e


def test_input_filter_counts_each_event_once():
    rec = Recorder()
    rec.start()
    viewport, panel = QWidget(), QWidget()
    inside, label, done = QWidget(viewport), QLabel("hint", panel), QPushButton("Done ▸", panel)
    f = InputFilter(rec, viewport)
    press = _mouse(100)
    f.eventFilter(label, press)
    f.eventFilter(panel, press)                     # the ignored press re-sent to the parent: one click
    f.eventFilter(inside, _mouse(101))              # viewport presses are reported by the viewport
    f.eventFilter(done, _mouse(102))
    f.eventFilter(done, _mouse(103, QEvent.Type.MouseButtonDblClick))  # 2nd click of a double-click
    key = _key(104)
    f.eventFilter(inside, key)
    f.eventFilter(viewport, key)
    f.eventFilter(inside, _key(105, repeat=True))
    assert rec.counts == {"gui": 3, "axis": 0, "gizmo": 0, "view": 0, "key": 1}
    assert [e["detail"] for e in rec.events if e["kind"] == "gui"] == ["QLabel", "Done ▸", "Done ▸"]
    assert [e["repeat"] for e in rec.events if e["kind"] == "key"] == [False, True]


if __name__ == "__main__":
    test_input_filter_counts_each_event_once()
    print("ok")
```

- [ ] **Step 2: Run, expect ImportError** — `.venv/bin/python -m tests.test_input_filter`

- [ ] **Step 3: Implement `InputFilter`** (window.py, after `TeeStream`)

```python
class InputFilter(QObject):
    """Study mode: logs panel clicks ("gui") and every key press, app-wide. Viewport presses are reported
    by the viewport itself. Qt re-sends an ignored event to each parent widget, so an event is counted
    once (same type and timestamp)."""

    PRESSES = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)

    def __init__(self, recorder, viewport):
        super().__init__()
        self.recorder, self.viewport = recorder, viewport
        self._last = None

    def eventFilter(self, obj, event):  # noqa: N802 (Qt API name)
        kind = event.type()
        if not isinstance(obj, QWidget) or (kind not in self.PRESSES and kind != QEvent.Type.KeyPress):
            return False
        stamp = (kind, event.timestamp())
        if stamp == self._last:
            return False
        self._last = stamp
        if kind == QEvent.Type.KeyPress:
            self.recorder.log("key", QKeySequence(event.key()).toString(), event.isAutoRepeat())
        elif obj is not self.viewport and not self.viewport.isAncestorOf(obj):
            self.recorder.log("gui", obj.text() if isinstance(obj, QAbstractButton) else type(obj).__name__)
        return False
```

- [ ] **Step 4: Run, expect `ok`** — `.venv/bin/python -m tests.test_input_filter`

- [ ] **Step 5: Study mode in `MainWindow`**

- `__init__(self, minimal=False, study=None)`: store `self.study = study`; after the existing setup,
  `if study: self._setup_study()`.
- `_build_ui`: keep references `self._header` (header layout), `self._panel` (panel layout),
  `self._chips = (object_chip, profile_chip, self.stem_chip)`, `self._dividers` (the dividers).
- `_mount`: `step = ... if self.current_stage else None`; after `set_widget`, `if self.study:
  self.recorder.start()`.
- `_finish_scene`: first line after the `None` guard: `if self.study: self.recorder.stop()`; step guard
  as in `_mount`.
- `_on_event`: `elif kind == "trial_end": self._end_trial(payload)`.
- `closeEvent`: treat an alive `self._trial_thread` like `self.runner.busy`.

```python
    # --- study mode ---
    def _setup_study(self) -> None:
        now = datetime.now()
        self.study_stamp, self.study_started = now.strftime("%Y%m%d_%H%M%S"), now.isoformat(timespec="seconds")
        self.recorder = st.Recorder()
        self.records, self.trial_i, self._trial_thread = [], 0, None
        self.viewport.on_input = self.recorder.log
        self._input_filter = InputFilter(self.recorder, self.viewport)
        QApplication.instance().installEventFilter(self._input_filter)
        for w in (self.run_btn, self.stop_btn, self.minimal_box, self.capture_btn, self.elapsed, self.timeline,
                  self.editor, *self._chips, *self._dividers[:2]):
            w.hide()
        self._panel.setStretchFactor(self.interaction, 1)
        self.study_label = QLabel("", objectName="ChipValue")
        self.trial_btn = QPushButton("Start trial ▸")
        self.trial_btn.setProperty("primary", True)
        self.trial_btn.clicked.connect(self._start_trial)
        self._header.insertWidget(2, self.study_label)
        self._header.insertWidget(self._header.count() - 1, self.trial_btn)
        self.setWindowTitle(f"RORA · study {self.study['participant']}")
        print(f"[info]: study {self.study['participant']}: results go to export/study/{self.study_stamp}/ "
              f"and working/study/{self.study_stamp}/")
        self._show_trial()

    def _show_trial(self) -> None:
        trials, who = self.study["trials"], self.study["participant"]
        if self.trial_i >= len(trials):
            self.study_label.setText(f"{who} · session complete")
            self.trial_btn.hide()
            self.interaction.set_idle(f"Session complete. Results: export/study/{self.study_stamp}/")
            return
        t = trials[self.trial_i]
        self.study_label.setText(f"{who} · trial {t['index']}/{len(trials)} · {t['object']} · {t['condition']}")
        self.trial_btn.setText("Start trial ▸" if self.trial_i == 0 else "Next trial ▸")
        self.trial_btn.setEnabled(True)
        self.interaction.set_idle("Press Start when you are ready.")

    def _start_trial(self) -> None:
        if self._trial_thread is not None and self._trial_thread.is_alive():
            return
        self.trial_btn.setEnabled(False)
        self.interaction.set_idle("Loading…")
        self.bridge.reset_stop()
        self._trial_started = datetime.now().isoformat(timespec="seconds")
        trial = self.study["trials"][self.trial_i]
        self._trial_thread = threading.Thread(target=self._trial_worker, args=(trial,), daemon=True, name="study")
        self._trial_thread.start()

    def _trial_worker(self, trial: dict) -> None:
        set_ui(self.bridge)
        try:
            result = st.run_trial(trial)
        except PipelineStopped:
            return
        except Exception:
            self.bridge.post("trial_end", {"error": traceback.format_exc()})
            return
        self.bridge.post("trial_end", {"result": result})

    def _end_trial(self, payload: dict) -> None:
        trial = self.study["trials"][self.trial_i]
        if "error" in payload:
            print(payload["error"])
            self.log.set_expanded(True)
            self.interaction.set_idle("Trial failed (see the log). Fix the inputs, then retry.")
            self.trial_btn.setText("Retry trial ▸")
            self.trial_btn.setEnabled(True)
            return
        joints, manual_pairs, suggestions = payload["result"]
        record = st.trial_record(self.study, trial, self._trial_started, self.recorder, joints, manual_pairs)
        try:
            path = st.save_trial(self.study, self.study_stamp, self.study_started, self.records, record, suggestions)
            print(f"[info]: trial {trial['index']} saved to {os.path.relpath(path, st.ROOT)}")
        except OSError as e:  # keep the data: the record goes to the terminal/log instead
            print(yaml.safe_dump(record, sort_keys=False))
            QMessageBox.critical(self, "Save failed", f"{e}\nThe trial record was printed to the log.")
        self.trial_i += 1
        self._show_trial()
```

Imports in window.py: `threading`, `from datetime import datetime`, `yaml`, `QEvent` (QtCore),
`QKeySequence` (QtGui), `QAbstractButton` (QtWidgets), `from functions.gui import study as st`,
`from functions.gui.bridge import PipelineStopped, UiBridge, set_ui`.

- [ ] **Step 6: `--study` in `app.py`**

```python
    parser.add_argument("--study", metavar="FILE",
                        help="user study mode: run the articulation trials listed in FILE (cfgs/study/example.yml)")
    ...
    study = None
    if args.study:
        import yaml
        from functions.gui.study import load_study
        try:
            study = load_study(args.study)
        except (OSError, ValueError, yaml.YAMLError) as e:
            print(f"[error]: {e}")
            return 1
    ...
    window = MainWindow(minimal=args.minimal, study=study)
```

- [ ] **Step 7: Verify** — all test modules (`.venv/bin/python -m tests.<m>` for every file in `tests/`)
  print `ok`; the scene and viewport smokes exit 0; an offscreen launch with a temp study file builds the
  window in study mode (Task 7).

### Task 7: End-to-end check (offscreen)

- [ ] **Step 1:** With a temp manifest/study under the scratchpad (`fan` A then B), construct
  `MainWindow(study=load_study(...))` offscreen, click Start, wait for the scene, simulate
  `scene.on_pick` on a triad arrow after `_new()`, `_confirm()`, `_done()`; then trial 2 with
  `JointSelectScene` → `finish()`. Check `export/study/<stamp>/session.yml` has 2 rows and
  `working/study/<stamp>/fan/02_B_suggestions.json` exists; then delete that stamp folder.
