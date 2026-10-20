import threading

from functions.gui import bridge
from functions.gui.bridge import NullBridge, PipelineStopped, StageTimer, UiBridge


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_timer_compute_excludes_wait():
    clock = FakeClock()
    timer = StageTimer(clock)
    timer.begin_stage("refine")
    assert timer.begin_step("a") is None
    clock.t += 2.0
    assert timer.begin_step("b") == ("a", 2.0)
    clock.t += 6.0
    timer.add_wait(5.0)
    assert timer.end_stage() == ("b", 1.0)
    r = timer.report()["refine"]
    assert (r["wall"], r["wait"], r["compute"]) == (8.0, 5.0, 3.0)
    assert r["steps"] == {"a": {"compute": 2.0, "wait": 0.0}, "b": {"compute": 1.0, "wait": 5.0}}
    assert "refine" in timer.summary()


def test_repeated_step_accumulates_and_stage_rerun_replaces():
    clock = FakeClock()
    timer = StageTimer(clock)
    timer.begin_stage("refine")
    timer.begin_step("load"); clock.t += 1.0
    timer.begin_step("save"); clock.t += 1.0
    timer.begin_step("load"); clock.t += 2.0
    timer.end_stage()
    assert timer.report()["refine"]["steps"]["load"]["compute"] == 3.0
    timer.begin_stage("refine"); clock.t += 0.5; timer.end_stage()
    assert timer.report()["refine"]["wall"] == 0.5 and timer.report()["refine"]["steps"] == {}


def test_events_and_interact_result():
    events = []
    b = UiBridge(lambda kind, payload: events.append((kind, payload)))
    b.begin_stage("segment")
    b.plan([("load", "Load", True)])
    b.step("load")
    threading.Timer(0.05, lambda: b.resolve("owners")).start()
    assert b.interact("scene-object") == "owners"
    b.end_stage("segment", "done")
    kinds = [k for k, _ in events]
    assert kinds == ["stage_begin", "plan", "step", "scene", "stage_end"]
    end = events[-1][1]
    assert end["name"] == "segment" and end["status"] == "done" and end["closed"][0] == "load"
    assert end["report"]["wait"] > 0.0


def test_stop_unblocks_waiting_worker():
    b = UiBridge(lambda kind, payload: None)
    b.begin_stage("segment")
    threading.Timer(0.05, b.request_stop).start()
    try:
        b.interact("scene")
        raise AssertionError("expected PipelineStopped")
    except PipelineStopped:
        pass
    try:
        b.step("next")
        raise AssertionError("expected PipelineStopped")
    except PipelineStopped:
        pass
    b.reset_stop()
    b.step("next")  # no longer stopped


def test_checkpoint_is_noop_unless_debug():
    events = []
    b = UiBridge(lambda kind, payload: events.append(kind))
    b.begin_stage("refine")
    b.checkpoint("title", lambda: [])
    assert "checkpoint" not in events
    b.debug = True
    threading.Timer(0.05, b.resolve).start()
    b.checkpoint("title", lambda: [])
    assert "checkpoint" in events


def test_default_ui_is_null_bridge():
    assert isinstance(bridge.ui(), NullBridge)
    bridge.ui().step("x")
    try:
        bridge.ui().interact("scene")
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
