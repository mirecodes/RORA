"""Main window: header, viewport | side panel, and the wiring between the bridge events, the runner,
the panel widgets, and the viewport."""
import copy
import sys
import time
import traceback

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QSplitter, QToolButton, QVBoxLayout, QWidget)

from functions.gui import theme as th
from functions.gui.bridge import UiBridge
from functions.gui.panel import InteractionHost, LogView, ParamEditor, Timeline
from functions.gui.params_io import list_object_profiles, load_comments, resolve_object_edit, save_object_profile
from functions.gui.runner import (STAGE_LABELS, STAGE_ORDER, PipelineRunner, first_blocked, initial_statuses,
                                  producer_labels, read_states, stale_after, stages_from)
from functions.gui.scenes import CheckpointScene
from functions.gui.viewport import Viewport
from functions.pipeline.interface import SystemConfigs, run_stage
from functions.utils.config import _merge, load_object, load_params, object_profile_params

PANEL_FRACTION, PANEL_MIN, PANEL_MAX = 0.22, 300, 380


class Signals(QObject):
    event = Signal(str, object)   # bridge events (worker -> GUI, queued)
    log = Signal(str)             # stdout/stderr tee (full mode only)


class TeeStream:
    """Writes to the original stream and forwards the text to the log panel."""

    def __init__(self, original, emit):
        self.original, self.emit = original, emit

    def write(self, text: str) -> int:
        self.original.write(text)
        if text:
            self.emit(text)
        return len(text)

    def flush(self) -> None:
        self.original.flush()

    def __getattr__(self, name):
        return getattr(self.original, name)


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    return line


class MainWindow(QMainWindow):
    def __init__(self, minimal: bool = False):
        super().__init__()
        self.setWindowTitle("RORA")
        self.resize(1600, 900)
        self.signals = Signals()
        self.bridge = UiBridge(self.signals.event.emit, minimal=minimal)
        self.runner = PipelineRunner(self.bridge, self.make_cfgs, run_stage)
        self.scene = None
        self.current_stage = None
        self.statuses = {}
        self._streams = (sys.stdout, sys.stderr)
        self._run_t0 = None
        self._build_ui()
        self.signals.event.connect(self._on_event)
        self.signals.log.connect(self.log.append)
        self._load(load_object())
        self.apply_theme(th.current())
        self.minimal_box.setChecked(minimal)
        self._set_minimal(minimal)
        self._clock = QTimer(self, interval=1000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()
        self._flush = QTimer(self, interval=250)
        self._flush.timeout.connect(self._flush_timeline)

    # --- layout ---
    def _build_ui(self) -> None:
        header = QWidget(objectName="Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 6, 12, 6)
        title = QLabel("RORA", objectName="Title")
        self.subtitle = QLabel("", objectName="Muted")
        self.run_btn = QPushButton("▶ Run")
        self.run_btn.setProperty("primary", True)
        self.stop_btn = QPushButton("■ Stop")
        self.minimal_box = QCheckBox("Minimal")
        self.minimal_box.setToolTip("No debug checkpoints, no live viewport while computing, terminal-only log")
        self.elapsed = QLabel("", objectName="Meta")
        self.theme_btn = QToolButton(text="◐", toolTip="Toggle light/dark theme")
        self.run_btn.clicked.connect(self.run_all)
        self.stop_btn.clicked.connect(self.stop)
        self.minimal_box.toggled.connect(self._set_minimal)
        self.theme_btn.clicked.connect(self.toggle_theme)
        for w in (title, self.subtitle):
            h.addWidget(w)
        h.addStretch()
        for w in (self.run_btn, self.stop_btn, self.minimal_box, self.elapsed, self.theme_btn):
            h.addWidget(w)

        self.viewport = Viewport()
        panel = QWidget(objectName="Panel")
        panel.setMinimumWidth(PANEL_MIN)
        panel.setMaximumWidth(PANEL_MAX)
        p = QVBoxLayout(panel)
        p.setContentsMargins(0, 0, 0, 0)
        p.setSpacing(0)
        self.timeline = Timeline()
        self.interaction = InteractionHost()
        self.editor = ParamEditor()
        self.log = LogView()
        for i, w in enumerate((self.timeline, self.interaction, self.editor, self.log)):
            if i:
                p.addWidget(_divider())
            p.addWidget(w, 1 if w is self.editor else 0)

        self.timeline.rerun.connect(self.rerun)
        self.timeline.run_from.connect(self.run_from)
        self.timeline.toggled.connect(self.editor.set_stage_enabled)
        self.timeline.selected.connect(self.editor.show_stage)
        self.editor.changed.connect(self._snapshot)
        self.editor.object_changed.connect(self._reload_object)
        self.editor.save_requested.connect(self.save_profile)

        split = QSplitter()
        split.addWidget(self.viewport)
        split.addWidget(panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        width = int(min(max(1600 * PANEL_FRACTION, PANEL_MIN), PANEL_MAX))
        split.setSizes([1600 - width, width])
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(header)
        v.addWidget(split, 1)
        self.setCentralWidget(central)
        self.stop_btn.setEnabled(False)

    # --- configs ---
    def _load(self, obj: dict, params: dict | None = None) -> None:
        stem = obj.get("object_profile") or ""
        params = params or load_params(profile=obj.get("profile"), object_profile=stem)
        self.editor.load(obj, params, load_comments(), list_object_profiles(obj["object_name"]))
        self._snapshot()
        cfgs = self.make_cfgs()
        self.states_path = cfgs.json_states_dir
        self.statuses = initial_statuses(read_states(self.states_path))
        self.timeline.reset(self.statuses, params["pipeline"]["stages"])
        self.subtitle.setText(f"{obj['object_name']} · profile: {obj.get('profile')}" + (f" · {stem}" if stem else ""))

    def _snapshot(self) -> None:
        """Hand the worker a private copy; it is read once per stage start (atomic reference swap)."""
        self._obj, self._params = self.editor.values()

    def make_cfgs(self) -> SystemConfigs:
        return SystemConfigs(obj=copy.deepcopy(self._obj), params=copy.deepcopy(self._params))

    def _reload_object(self, edited: dict) -> None:
        obj = resolve_object_edit(self._obj, edited)
        stem = obj.get("object_profile") or ""
        pipeline = copy.deepcopy(self._params["pipeline"])
        params = load_params(profile=obj.get("profile"), object_profile="")
        if stem:
            params = _merge(params, object_profile_params(stem))
        params["pipeline"] = pipeline  # run settings survive an object switch
        self._load(obj, params)

    def save_profile(self) -> None:
        obj, params = self.editor.values()
        try:
            stem = save_object_profile(params, obj)
        except Exception as e:  # keep the GUI alive; nothing is written on failure
            QMessageBox.critical(self, "Save failed", str(e))
            return
        obj["object_profile"] = stem
        self.editor.after_save(obj, list_object_profiles(obj["object_name"]))
        self._snapshot()
        self.subtitle.setText(f"{obj['object_name']} · profile: {obj.get('profile')} · {stem}")
        print(f"[info]: saved object profile cfgs/profiles/objects/{stem}.yml")

    # --- run control ---
    def run_all(self) -> None:
        self._start([s for s in STAGE_ORDER if self._params["pipeline"]["stages"].get(s)])

    def rerun(self, stage: str) -> None:
        self._start([stage])

    def run_from(self, stage: str) -> None:
        self._start(stages_from(stage, self._params["pipeline"]["stages"]))

    def _start(self, stages: list[str]) -> None:
        if self.runner.busy or not stages:
            return
        blocked = first_blocked(stages, read_states(self.states_path), self._params["pipeline"]["restore_align"])
        if blocked:
            stage, missing = blocked
            QMessageBox.warning(self, "Cannot run",
                                f"{STAGE_LABELS[stage]} needs results from {', '.join(producer_labels(missing))}, "
                                f"which have not run for this object yet. Run them first.")
            return
        self.statuses = stale_after(self.statuses, stages[0])
        for stage, status in self.statuses.items():
            self.timeline.rows[stage].set_status(status)
        self._set_busy(True)
        self.runner.start(stages)

    def stop(self) -> None:
        self.bridge.request_stop()
        self.stop_btn.setText("Stopping…")

    def _set_busy(self, busy: bool) -> None:
        self.run_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)
        self.minimal_box.setEnabled(not busy)
        self.timeline.set_busy(busy)
        self.editor.set_busy(busy)
        self._run_t0 = time.monotonic() if busy else None
        if busy and self.bridge.minimal:
            self.timeline.setUpdatesEnabled(False)
            self._flush.start()
        else:
            self._flush.stop()
            self.timeline.setUpdatesEnabled(True)

    def _set_minimal(self, on: bool) -> None:
        self.bridge.minimal = on
        if on:
            sys.stdout, sys.stderr = self._streams
        else:
            sys.stdout = TeeStream(self._streams[0], self.signals.log.emit)
            sys.stderr = TeeStream(self._streams[1], self.signals.log.emit)

    def _flush_timeline(self) -> None:
        """Minimal mode: repaint the timeline at 4 Hz instead of on every event."""
        self.timeline.setUpdatesEnabled(True)
        self.timeline.repaint()
        self.timeline.setUpdatesEnabled(False)

    def _tick(self) -> None:
        if self._run_t0 is not None:
            s = int(time.monotonic() - self._run_t0)
            self.elapsed.setText(f"{s // 60:02d}:{s % 60:02d}")

    # --- bridge events ---
    def _on_event(self, kind: str, payload) -> None:
        if kind == "stage_begin":
            self.current_stage = payload
            self.statuses[payload] = "running"
            self.timeline.set_status(payload, "running")
            self.interaction.set_idle("Computing…")
            self.viewport.suspend(self.bridge.minimal)
        elif kind == "plan":
            self.timeline.add_plan(self.current_stage, payload)
        elif kind == "step":
            closed = payload["closed"]
            if closed:
                self.timeline.set_step(self.current_stage, closed[0], "done", f"{closed[1]:.1f}s")
            self.timeline.set_step(self.current_stage, payload["key"], "running")
        elif kind in ("scene", "checkpoint"):
            scene = payload if kind == "scene" else CheckpointScene(*payload)
            self._mount(scene, "⏸ input" if kind == "scene" else "⏸ checkpoint")
        elif kind == "stage_end":
            if self.scene is not None:  # stopped while waiting for input
                self.scene = None
                self.viewport.unmount()
            name, status = payload["name"], payload["status"]
            self.statuses[name] = status
            compute = (payload["report"] or {}).get("compute", 0.0)
            self.timeline.finish(name, status, compute, payload["closed"])
            if payload["error"]:
                self.log.set_expanded(True)
        elif kind == "run_end":
            self._set_busy(False)
            self.interaction.set_idle("Idle")
            self.stop_btn.setText("■ Stop")
            self.viewport.suspend(False)

    def _mount(self, scene, waiting: str) -> None:
        step = self.timeline.current_step(self.current_stage)
        if step:
            self.timeline.set_step(self.current_stage, step, "waiting", waiting)
        scene.finish = self._finish_scene
        self.scene = scene
        try:
            self.viewport.mount(scene)
            self.interaction.set_widget(scene.widget())
        except Exception:
            # never leave the worker blocked: fail the stage with the GUI-side traceback
            self.scene = None
            self.viewport.unmount()
            self.bridge.fail(traceback.format_exc())

    def _finish_scene(self) -> None:
        if self.scene is None:
            return
        result = self.scene.result()
        self.scene = None
        self.viewport.unmount()
        self.interaction.set_idle("Computing…")
        step = self.timeline.current_step(self.current_stage)
        if step:
            self.timeline.set_step(self.current_stage, step, "running")
        self.viewport.suspend(self.bridge.minimal)
        self.bridge.resolve(result)

    # --- theme / close ---
    def toggle_theme(self) -> None:
        self.apply_theme(th.LIGHT if th.current() is th.DARK else th.DARK)

    def apply_theme(self, t) -> None:
        th.set_current(t)
        QApplication.instance().setStyleSheet(th.stylesheet(t))
        self.viewport.apply_theme(t)
        self.timeline.update()

    def closeEvent(self, event):  # noqa: N802 (Qt API name)
        if self.runner.busy:
            answer = QMessageBox.question(self, "Quit RORA", "A run is active. Stop it and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.bridge.request_stop()
        sys.stdout, sys.stderr = self._streams
        self.viewport.close_vtk()
        event.accept()
