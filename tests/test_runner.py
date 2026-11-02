import os
import tempfile
import threading
import time
from types import SimpleNamespace

import yaml

from functions.gui import runner as r
from functions.gui.bridge import UiBridge, ui


def make_runner(run_stage, debug_mode=False, minimal=False, on_event=None):
    tmp = tempfile.mkdtemp()
    events = []

    def post(kind, payload):
        events.append((kind, payload))
        if on_event:
            on_event(kind, payload)

    bridge = UiBridge(post, minimal=minimal)
    cfgs = SimpleNamespace(debug_mode=debug_mode, json_attr_dir=tmp, out_dir=os.path.join(tmp, "export"))
    return r.PipelineRunner(bridge, lambda: cfgs, run_stage), bridge, events, tmp


def ends(events):
    return {p["name"]: p["status"] for k, p in events if k == "stage_end"}


def test_runs_in_order_and_writes_timing():
    calls = []
    runner, _, events, tmp = make_runner(lambda cfgs, name: calls.append(name))
    runner.start(["align", "refine"])
    runner.join(5)
    assert calls == ["align", "refine"]
    assert ends(events) == {"align": "done", "refine": "done"}
    assert events[-1] == ("run_end", None)
    with open(os.path.join(tmp, "timing.yml"), encoding="utf-8") as f:
        timing = yaml.safe_load(f)
    assert set(timing["stages"]) == {"align", "refine"} and timing["minimal"] is False
    with open(os.path.join(tmp, "export", "timing.yml"), encoding="utf-8") as f:
        assert yaml.safe_load(f) == timing  # the same timing next to the outputs


def test_failure_stops_the_run():
    calls = []

    def run_stage(cfgs, name):
        calls.append(name)
        if name == "refine":
            raise ValueError("boom")

    runner, _, events, _ = make_runner(run_stage)
    runner.start(["align", "refine", "decompose"])
    runner.join(5)
    assert calls == ["align", "refine"]
    end = [p for k, p in events if k == "stage_end"][-1]
    assert end["status"] == "failed" and "boom" in end["error"]


def test_stop_while_waiting_for_input():
    def run_stage(cfgs, name):
        ui().step("select")
        ui().interact("scene")

    def on_event(kind, payload):
        if kind == "scene":
            threading.Timer(0.05, bridge.request_stop).start()

    runner, bridge, events, _ = make_runner(run_stage, on_event=on_event)
    runner.start(["segment", "articulate"])
    runner.join(5)
    assert ends(events) == {"segment": "stopped"}


def test_stop_during_long_call_ends_at_next_step():
    def run_stage(cfgs, name):
        ui().step("native")
        time.sleep(0.2)  # stands in for CoACD / Poisson
        ui().step("save")

    runner, bridge, events, _ = make_runner(run_stage)
    runner.start(["decompose"])
    time.sleep(0.05)
    bridge.request_stop()
    runner.join(5)
    assert not runner.busy
    assert ends(events) == {"decompose": "stopped"}


def test_debug_follows_cfgs_and_minimal():
    seen = []
    runner, bridge, _, _ = make_runner(lambda c, n: seen.append(ui().debug), debug_mode=True)
    runner.start(["align"]); runner.join(5)
    runner2, _, _, _ = make_runner(lambda c, n: seen.append(ui().debug), debug_mode=True, minimal=True)
    runner2.start(["align"]); runner2.join(5)
    assert seen == [True, False]


def test_first_blocked_names_missing_upstream():
    assert r.first_blocked(["segment"], {}) == ("segment", ["refine", "decompose"])
    assert r.first_blocked(["align", "refine", "decompose"], {}) is None
    assert r.first_blocked(["decompose"], {"refine": {"dirs": {}}}) is None
    assert r.first_blocked(["align"], {}, restore_align=True) == ("align", ["transform"])
    assert r.producer_labels(["refine", "decompose"]) == ["Refine", "Decompose"]
    assert r.producer_labels(["transform"]) == ["Align"]


def test_statuses_helpers():
    states = {"transform": {"m": 1}, "refine": {"d": 1}}
    st = r.initial_statuses(states)
    assert st["align"] == "cached" and st["refine"] == "cached" and st["decompose"] == "pending"
    st.update(decompose="done", segment="done", bind="pending")
    after = r.stale_after(st, "refine")
    assert after["align"] == "cached" and after["refine"] == "cached"
    assert after["decompose"] == "stale" and after["segment"] == "stale" and after["bind"] == "pending"
    enabled = {"align": True, "refine": True, "decompose": False, "segment": True,
               "articulate": True, "bind": False}
    assert r.stages_from("decompose", enabled) == ["decompose", "segment", "articulate"]


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
