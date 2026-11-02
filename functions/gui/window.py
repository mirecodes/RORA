"""Main window: header, viewport | side panel, and the wiring between the bridge events, the runner,
the panel widgets, and the viewport."""
import copy
import os
import sys
import threading
import time
import traceback
from datetime import datetime

import yaml
from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QSplitter, QToolButton, QVBoxLayout, QWidget)

from functions.gui import study as st
from functions.gui import theme as th
from functions.gui.bridge import PipelineStopped, UiBridge, set_ui
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


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    return line


def _chip(caption: str) -> tuple[QFrame, QLabel]:
    """Shaded header field: small caption + value."""
    chip = QFrame(objectName="Chip")
    row = QHBoxLayout(chip)
    row.setContentsMargins(8, 3, 8, 3)
    row.setSpacing(6)
    value = QLabel("", objectName="ChipValue")
    row.addWidget(QLabel(caption.upper(), objectName="ChipKey"))
    row.addWidget(value)
    return chip, value


class MainWindow(QMainWindow):
    def __init__(self, minimal: bool = False, study: dict | None = None):
        super().__init__()
        self.setWindowTitle("RORA")
        self.resize(1600, 900)
        self.study = study        # functions.gui.study.load_study() result, or None
        self._trial_thread = None
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
        if study:
            self._setup_study()

    # --- layout ---
    def _build_ui(self) -> None:
        header = QWidget(objectName="Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(8)
        title = QLabel("RORA", objectName="Title")
        object_chip, self.object_label = _chip("Object")
        profile_chip, self.profile_label = _chip("Profile")
        self.stem_chip, self.stem_label = _chip("Object profile")
        self.run_btn = QPushButton("▶ Run")
        self.run_btn.setProperty("primary", True)
        self.stop_btn = QPushButton("■ Stop")
        self.capture_btn = QPushButton("Capture")
        self.capture_btn.setToolTip("Save the current view as a square PNG to export/<object>/captures")
        self.minimal_box = QCheckBox("Minimal", objectName="Mode")
        self.minimal_box.setToolTip("No debug checkpoints, no live viewport while computing, terminal-only log")
        self.elapsed = QLabel("", objectName="Meta")
        self.theme_btn = QToolButton(text="◐", toolTip="Toggle light/dark theme")
        self.run_btn.clicked.connect(self.run_all)
        self.stop_btn.clicked.connect(self.stop)
        self.capture_btn.clicked.connect(self.capture)
        self.minimal_box.toggled.connect(self._set_minimal)
        self.theme_btn.clicked.connect(self.toggle_theme)
        h.addWidget(title)
        h.addSpacing(8)
        self._header, self._chips = h, (object_chip, profile_chip, self.stem_chip)
        for w in self._chips:
            h.addWidget(w)
        h.addStretch()
        for w in (self.capture_btn, self.run_btn, self.stop_btn, self.minimal_box, self.elapsed, self.theme_btn):
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
        self._panel, self._dividers = p, []
        for i, w in enumerate((self.timeline, self.interaction, self.editor, self.log)):
            if i:
                self._dividers.append(_divider())
                p.addWidget(self._dividers[-1])
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
        self._show_object(obj)

    def _show_object(self, obj: dict) -> None:
        self.object_label.setText(obj["object_name"])
        self.object_label.parentWidget().setToolTip(self.make_cfgs().mesh_in_dir)
        self.profile_label.setText(str(obj.get("profile")))
        self.stem_label.setText(obj.get("object_profile") or "")
        self.stem_chip.setVisible(bool(obj.get("object_profile")))

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
        self._show_object(obj)
        print(f"[info]: saved object profile cfgs/profiles/objects/{stem}.yml")

    def capture(self) -> None:
        cfgs = self.make_cfgs()
        out_dir = os.path.join(cfgs.out_dir, "captures")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{cfgs.object_name}_{time.strftime('%Y%m%d_%H%M%S')}.png")
        try:
            self.viewport.capture(path)
        except Exception as e:  # keep the GUI alive
            QMessageBox.critical(self, "Capture failed", str(e))
            return
        print(f"[info]: saved capture {os.path.relpath(path, cfgs.root_dir)}")

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
            if self.study and kind == "scene":
                self._ready(scene)  # loaded; shown when the participant presses Start
            else:
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
        elif kind == "trial_end":
            self._end_trial(payload)

    def _mount(self, scene, waiting: str) -> None:
        step = self.timeline.current_step(self.current_stage) if self.current_stage else None
        if step:
            self.timeline.set_step(self.current_stage, step, "waiting", waiting)
        scene.finish = self._finish_scene
        self.scene = scene
        try:
            self.viewport.mount(scene)
            self.interaction.set_widget(scene.widget())
            if self.study:
                self.recorder.start()  # a trial is timed from Start (scene appears) until Done
        except Exception:
            # never leave the worker blocked: fail the stage with the GUI-side traceback
            self.scene = None
            self.viewport.unmount()
            self.bridge.fail(traceback.format_exc())

    def _finish_scene(self) -> None:
        if self.scene is None:
            return
        if self.study:
            self.recorder.stop()
        result = self.scene.result()
        self.scene = None
        self.viewport.unmount()
        self.interaction.set_idle("Computing…")
        step = self.timeline.current_step(self.current_stage) if self.current_stage else None
        if step:
            self.timeline.set_step(self.current_stage, step, "running")
        self.viewport.suspend(self.bridge.minimal)
        self.bridge.resolve(result)

    # --- study mode ---
    def _setup_study(self) -> None:
        now = datetime.now()
        name = os.path.splitext(os.path.basename(self.study["study_file"]))[0]  # cfgs/study/P01/P01.yml -> P01
        self.study_stamp = f"{name}_{now:%Y%m%d_%H%M%S}"
        self.study_started = now.isoformat(timespec="seconds")
        self.recorder = st.Recorder()
        self.records, self.trial_i, self._pending, self._skipping = [], 0, None, False
        self.viewport.on_input = self.recorder.log
        self._input_filter = InputFilter(self.recorder, self.viewport)
        QApplication.instance().installEventFilter(self._input_filter)
        for w in (self.run_btn, self.stop_btn, self.minimal_box, self.capture_btn, self.elapsed, self.timeline,
                  self.editor, *self._chips, *self._dividers[:2]):
            w.hide()
        self._panel.setStretchFactor(self.interaction, 1)
        self.study_label = QLabel("", objectName="ChipValue")
        self.trial_btn = QPushButton("▶ Start")
        self.trial_btn.setProperty("primary", True)
        self.trial_btn.clicked.connect(self._start_pressed)
        self._header.insertWidget(2, self.study_label)
        self._header.insertWidget(self._header.count() - 1, self.trial_btn)  # top right, before the theme toggle
        self.skip_btn = QPushButton("Skip ▸▸")
        self.skip_btn.clicked.connect(self._skip_pressed)
        self.skip_btn.setVisible(bool(self.study.get("tutorial")))
        self._header.insertWidget(self._header.count() - 1, self.skip_btn)
        self.setWindowTitle(f"RORA · study {self.study['participant']}")
        print(f"[info]: study {self.study['participant']}: results go to export/study/{self.study_stamp}/ "
              f"and working/study/{self.study_stamp}/")
        self._load_trial()

    def _load_trial(self) -> None:
        """Prepare the current trial in the background (B computes its suggestions here, untimed). The
        viewport stays empty until the participant presses Start."""
        trials, who = self.study["trials"], self.study["participant"]
        self.viewport.set_actors([])
        if self.trial_i >= len(trials):
            self.study_label.setText(f"{who} · session complete")
            self.trial_btn.hide()
            self.skip_btn.hide()
            self.interaction.set_idle(f"Session complete. Results: export/study/{self.study_stamp}/")
            return
        t = trials[self.trial_i]
        self.study_label.setText(f"{who} · trial {t['index']}/{len(trials)} · {t['object']} · {t['condition']}")
        self.trial_btn.setText("▶ Start")
        self.trial_btn.setEnabled(False)
        self.interaction.set_idle(f"Preparing trial {t['index']}…")
        self.bridge.reset_stop()
        self._trial_thread = threading.Thread(target=self._trial_worker, args=(t,), daemon=True, name="study")
        self._trial_thread.start()

    def _ready(self, scene) -> None:
        if self._skipping:  # posted just as Skip was pressed (the stop may have been missed): release it
            self.bridge.request_stop()
            return
        self._pending = scene
        self.trial_btn.setEnabled(True)
        self.interaction.set_idle("Ready. Press ▶ Start (top right) to begin.")

    def _start_pressed(self) -> None:
        if self._pending is not None:
            scene, self._pending = self._pending, None
            self.trial_btn.setEnabled(False)
            self.trial_btn.setText("● In progress")
            self._trial_started = datetime.now().isoformat(timespec="seconds")
            self._mount(scene, "⏸ input")
        elif self._trial_thread is None or not self._trial_thread.is_alive():
            self._load_trial()  # retry after a failure

    def _skip_pressed(self) -> None:
        """Tutorial: drop the current trial unsaved. Stops its worker; _end_trial moves on once it exits."""
        if self._trial_thread is None or not self._trial_thread.is_alive():  # failed, waiting for Retry
            self.trial_i += 1
            self._load_trial()
            return
        self._skipping, self._pending = True, None
        self.skip_btn.setEnabled(False)
        if self.scene is not None:
            self.recorder.stop()
            self.scene = None
            self.viewport.unmount()
        self.bridge.request_stop()

    def _trial_worker(self, trial: dict) -> None:
        set_ui(self.bridge)
        try:
            result = st.run_trial(trial)
        except PipelineStopped:
            self.bridge.post("trial_end", {"skipped": True})
            return
        except Exception:
            self.bridge.post("trial_end", {"error": traceback.format_exc()})
            return
        self.bridge.post("trial_end", {"result": result})

    def _end_trial(self, payload: dict) -> None:
        trial = self.study["trials"][self.trial_i]
        if "skipped" in payload:  # also posted when closing the window; only Skip moves on
            if self._skipping:
                print(f"[info]: trial {trial['index']} skipped")
                self._skipping = False
                self.skip_btn.setEnabled(True)
                self.trial_i += 1
                self._load_trial()
            return
        if "error" in payload:
            print(payload["error"])
            self.log.set_expanded(True)
            self.interaction.set_idle("Trial failed (see the log). Fix the inputs, then retry.")
            self.trial_btn.setText("Retry ▸")
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
        self._load_trial()

    # --- theme / close ---
    def toggle_theme(self) -> None:
        self.apply_theme(th.LIGHT if th.current() is th.DARK else th.DARK)

    def apply_theme(self, t) -> None:
        th.set_current(t)
        QApplication.instance().setStyleSheet(th.stylesheet(t))
        self.viewport.apply_theme(t)
        self.timeline.update()

    def closeEvent(self, event):  # noqa: N802 (Qt API name)
        trial_busy = self._trial_thread is not None and self._trial_thread.is_alive()
        if self.runner.busy or trial_busy:
            answer = QMessageBox.question(self, "Quit RORA", "A run is active. Stop it and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.bridge.request_stop()
        sys.stdout, sys.stderr = self._streams
        self.viewport.close_vtk()
        event.accept()
