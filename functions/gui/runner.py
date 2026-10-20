"""Runs pipeline stages on a worker thread and reports through the UiBridge. Qt-free."""
import json
import os
import threading
import traceback
from datetime import datetime
from typing import Callable

from functions.gui.bridge import PipelineStopped, set_ui

STAGE_ORDER = ["align", "refine", "decompose", "segment", "articulate", "bind"]
STAGE_LABELS = {"align": "Align", "refine": "Refine", "decompose": "Decompose", "segment": "Segment",
                "articulate": "Articulate", "bind": "Bind"}
# states.json sections a stage reads, and the section it writes (bind writes only export files)
PREREQS = {"align": [], "refine": ["transform"], "decompose": ["refine"], "segment": ["refine", "decompose"],
           "articulate": ["refine", "segment"], "bind": ["transform", "refine", "segment"]}
PRODUCES = {"align": "transform", "refine": "refine", "decompose": "decompose", "segment": "segment",
            "articulate": "articulate", "bind": None}


def read_states(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def missing_prereqs(stage: str, available: set, restore_align: bool = False) -> list[str]:
    need = PREREQS[stage] + (["transform"] if stage == "align" and restore_align else [])
    return [k for k in need if k not in available]


def first_blocked(stages, states: dict, restore_align: bool = False):
    """(stage, missing sections) for the first stage whose inputs are neither in states.json nor
    produced earlier in this run; None when the run can start."""
    available = {k for k, v in states.items() if v}
    for stage in stages:
        missing = missing_prereqs(stage, available, restore_align)
        if missing:
            return stage, missing
        if PRODUCES[stage]:
            available.add(PRODUCES[stage])
    return None


def initial_statuses(states: dict) -> dict:
    return {s: "cached" if PRODUCES[s] and states.get(PRODUCES[s]) else "pending" for s in STAGE_ORDER}


def stale_after(statuses: dict, rerun: str) -> dict:
    """Finished stages downstream of `rerun` become 'stale'."""
    i = STAGE_ORDER.index(rerun)
    return {s: "stale" if STAGE_ORDER.index(s) > i and st in ("done", "cached") else st
            for s, st in statuses.items()}


def stages_from(stage: str, enabled: dict) -> list[str]:
    """`stage` itself plus every enabled stage after it."""
    i = STAGE_ORDER.index(stage)
    return [stage] + [s for s in STAGE_ORDER[i + 1:] if enabled.get(s)]


def write_timing(attr_dir: str, report: dict, started: str, minimal: bool) -> str:
    path = os.path.join(attr_dir, "timing.json")
    os.makedirs(attr_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"run_started": started, "minimal": minimal, "stages": report}, f, indent=2)
    return path


class PipelineRunner:
    """Runs stages on a daemon thread. make_cfgs() is called at every stage start, so each stage uses
    the parameters as they were when it started."""

    def __init__(self, bridge, make_cfgs: Callable, run_stage: Callable):
        self.bridge, self.make_cfgs, self.run_stage = bridge, make_cfgs, run_stage
        self._thread = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, stages) -> None:
        if self.busy:
            raise RuntimeError("A run is already active.")
        self.bridge.reset_stop()
        self._thread = threading.Thread(target=self._run, args=(list(stages),), daemon=True, name="pipeline")
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, stages) -> None:
        b = self.bridge
        set_ui(b)
        b.timer.reset()
        started = datetime.now().isoformat(timespec="seconds")
        cfgs = None
        try:
            for name in stages:
                b.begin_stage(name)
                try:
                    cfgs = self.make_cfgs()
                    b.debug = bool(cfgs.debug_mode) and not b.minimal
                    self.run_stage(cfgs, name)
                except PipelineStopped:
                    print(f"[info]: {name} stopped by the user.")
                    b.end_stage(name, "stopped")
                    break
                except Exception:
                    tb = traceback.format_exc()
                    print(tb)
                    b.end_stage(name, "failed", tb)
                    break
                b.end_stage(name, "done")
        finally:
            if cfgs is not None and b.timer.stages:
                print(b.timer.summary())
                write_timing(cfgs.json_attr_dir, b.timer.report(), started, b.minimal)
            b.post("run_end", None)
