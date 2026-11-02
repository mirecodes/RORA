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
            errors.append(f"trial {i}: {name} has no {', '.join(missing)} results in "
                          f"working/{name}/attributes/states.json")
        trials.append({"index": i, "object": name, "condition": cond, "entry": objects[name]})
    if not doc.get("trials"):
        errors.append("no trials listed")
    if errors:
        raise ValueError(f"{path}:\n  " + "\n  ".join(errors))
    path = os.path.abspath(path)
    inside = os.path.commonpath([path, os.path.abspath(root)]) == os.path.abspath(root)
    return {"participant": str(doc["participant"]), "study_file": os.path.relpath(path, root) if inside else path,
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
