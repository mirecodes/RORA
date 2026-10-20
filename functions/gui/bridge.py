"""Thread-safe bridge between pipeline stage code (worker thread) and the GUI (main thread).

Stage code only calls ui(). The GUI installs a UiBridge with set_ui(); without a GUI, ui() returns a
NullBridge, so stage modules stay importable and the non-interactive parts can run headless.
A future ReplayBridge (answers interact() from states.json) can be installed the same way."""
import threading
import time
from typing import Any, Callable


class PipelineStopped(Exception):
    """Raised in the worker thread when the user presses Stop."""


class StageTimer:
    """Per-stage and per-step wall time and wait time (blocked on user input). compute = wall - wait."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter):
        self.clock = clock
        self.reset()

    def reset(self) -> None:
        self.stages: dict[str, dict] = {}
        self._stage = None
        self._step = None
        self._t_stage = self._t_step = 0.0

    def begin_stage(self, name: str) -> None:
        self.end_stage()
        self._stage = name
        self.stages[name] = {"wall": 0.0, "wait": 0.0, "steps": {}}
        self._t_stage = self.clock()

    def _close_step(self):
        if self._step is None:
            return None
        step = self.stages[self._stage]["steps"][self._step]
        step["wall"] += self.clock() - self._t_step
        closed = (self._step, step["wall"] - step["wait"])
        self._step = None
        return closed

    def begin_step(self, key: str):
        """Start `key`; return (previous key, its compute seconds) or None."""
        if self._stage is None:
            return None
        closed = self._close_step()
        self._step = key
        self._t_step = self.clock()
        self.stages[self._stage]["steps"].setdefault(key, {"wall": 0.0, "wait": 0.0})
        return closed

    def add_wait(self, seconds: float) -> None:
        if self._stage is None:
            return
        stage = self.stages[self._stage]
        stage["wait"] += seconds
        if self._step is not None:
            stage["steps"][self._step]["wait"] += seconds

    def end_stage(self):
        """Close the stage; return its last step as (key, compute seconds) or None."""
        if self._stage is None:
            return None
        closed = self._close_step()
        self.stages[self._stage]["wall"] = self.clock() - self._t_stage
        self._stage = None
        return closed

    def report(self) -> dict:
        return {name: {"compute": s["wall"] - s["wait"], "wait": s["wait"], "wall": s["wall"],
                       "steps": {k: {"compute": v["wall"] - v["wait"], "wait": v["wait"]}
                                 for k, v in s["steps"].items()}}
                for name, s in self.stages.items()}

    def summary(self) -> str:
        rows = self.report()
        lines = ["=" * 44, f"{'Pipeline timing (seconds)':^44}", "=" * 44,
                 f"{'stage':<14}{'compute':>10}{'wait':>10}{'wall':>10}"]
        for name, r in rows.items():
            lines.append(f"{name:<14}{r['compute']:>10.2f}{r['wait']:>10.2f}{r['wall']:>10.2f}")
        total = [sum(r[k] for r in rows.values()) for k in ("compute", "wait", "wall")]
        lines += ["-" * 44, f"{'total':<14}{total[0]:>10.2f}{total[1]:>10.2f}{total[2]:>10.2f}", "=" * 44]
        return "\n".join(lines)


class NullBridge:
    """Headless default: progress calls are no-ops; interaction needs the GUI."""
    debug = False
    minimal = False

    def plan(self, steps) -> None:
        pass

    def step(self, key: str) -> None:
        pass

    def checkpoint(self, title: str, build) -> None:
        pass

    def check_stop(self) -> None:
        pass

    def interact(self, scene):
        raise RuntimeError("This stage needs user input. Start the GUI with scripts/run_pipeline.sh.")


class UiBridge:
    """Called from the worker thread. `post(kind, payload)` must hand events to the GUI thread
    (a Qt signal emit); interact()/checkpoint() block until the GUI calls resolve() or request_stop()."""

    def __init__(self, post: Callable[[str, Any], None], *, minimal: bool = False,
                 clock: Callable[[], float] = time.perf_counter):
        self.post = post
        self.minimal = minimal
        self.debug = False  # set by the runner per stage: cfgs.debug_mode and not minimal
        self.timer = StageTimer(clock)
        self._stop = threading.Event()
        self._done = threading.Event()
        self._result = None

    # --- runner side ---
    def begin_stage(self, name: str) -> None:
        self.timer.begin_stage(name)
        self.post("stage_begin", name)

    def end_stage(self, name: str, status: str, error: str | None = None) -> None:
        closed = self.timer.end_stage()
        self.post("stage_end", {"name": name, "status": status, "error": error,
                                "report": self.timer.report().get(name), "closed": closed})

    # --- stage side ---
    def plan(self, steps) -> None:
        """Declare (key, label, enabled) sub-steps; repeated calls append keys not seen yet."""
        self.post("plan", [tuple(s) for s in steps])

    def step(self, key: str) -> None:
        self.check_stop()
        self.post("step", {"key": key, "closed": self.timer.begin_step(key)})

    def checkpoint(self, title: str, build) -> None:
        """Show `build()` (run on the GUI thread) until Continue. No-op unless debug is on."""
        if self.debug:
            self._block("checkpoint", (title, build))

    def interact(self, scene):
        return self._block("scene", scene)

    def check_stop(self) -> None:
        if self._stop.is_set():
            raise PipelineStopped()

    def _block(self, kind: str, payload):
        self.check_stop()
        self._done.clear()
        self._result = None
        t0 = self.timer.clock()
        self.post(kind, payload)
        self._done.wait()
        self.timer.add_wait(self.timer.clock() - t0)
        self.check_stop()
        return self._result

    # --- GUI side ---
    def resolve(self, result=None) -> None:
        self._result = result
        self._done.set()

    def request_stop(self) -> None:
        self._stop.set()
        self._done.set()

    def reset_stop(self) -> None:
        self._stop.clear()


_active = NullBridge()


def ui():
    """The bridge stage code reports to (NullBridge until the GUI installs one)."""
    return _active


def set_ui(bridge) -> None:
    global _active
    _active = bridge
