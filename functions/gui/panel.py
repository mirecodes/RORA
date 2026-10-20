"""Side panel widgets: git-log style stage timeline, interaction host, parameter editor, and log."""
import copy

import yaml
from PySide6.QtCore import QPoint, QRegularExpression, Qt, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QPainter, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QScrollArea, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from functions.gui import theme as th
from functions.gui.params_io import STAGE_SECTIONS, field_kind
from functions.gui.runner import STAGE_LABELS, STAGE_ORDER
from functions.gui.scenes import section


def _set_state(widget: QWidget, state: str) -> None:
    """Set the `state` dynamic property and re-apply the stylesheet rules that depend on it."""
    widget.setProperty("state", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _label(text: str = "", name: str = "") -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    return label


class SubStepRow(QWidget):
    def __init__(self, key: str, label: str, enabled: bool):
        super().__init__()
        self.key = key
        self.dot = _label(name="SubDot")
        self.name = _label(label, "SubName")
        self.meta = _label("" if enabled else "off", "Meta")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 1, 0, 1)
        layout.setSpacing(8)
        layout.addWidget(self.dot)
        layout.addWidget(self.name)
        layout.addStretch()
        layout.addWidget(self.meta)
        self.state = ""
        self.set_state("pending" if enabled else "skipped")

    def set_state(self, state: str, meta: str | None = None) -> None:
        self.state = state
        _set_state(self.dot, state)
        _set_state(self.name, state)
        if meta is not None:
            self.meta.setText(meta)


class StageRow(QWidget):
    rerun = Signal(str)
    run_from = Signal(str)
    toggled = Signal(str, bool)
    clicked = Signal(str)

    def __init__(self, stage: str):
        super().__init__()
        self.stage = stage
        self.status = "pending"
        self.expanded = False
        self.busy = False
        self.subs: dict[str, SubStepRow] = {}

        self.check = QCheckBox()
        self.check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.check.setToolTip("Include this stage in ▶ Run")
        # Slots are bound methods: a lambda capturing `self` forms a cycle that can crash when GC'd.
        self.check.toggled.connect(self._emit_toggled)
        self.dot = _label(name="Dot")
        self.name = _label(STAGE_LABELS[stage], "StageName")
        self.summary = _label("", "Meta")
        self.rerun_btn = QToolButton(toolTip="Re-run this stage")
        self.from_btn = QToolButton(toolTip="Run from this stage")
        for b in (self.rerun_btn, self.from_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setFixedWidth(20)
        self.rerun_btn.clicked.connect(self._emit_rerun)
        self.from_btn.clicked.connect(self._emit_run_from)

        header = QHBoxLayout()
        header.setContentsMargins(0, 2, 0, 2)
        header.setSpacing(8)
        header.addWidget(self.check)
        header.addSpacing(4)
        header.addWidget(self.dot)
        header.addWidget(self.name)
        header.addStretch()
        for w in (self.summary, self.rerun_btn, self.from_btn):
            header.addWidget(w)
        self.sub_box = QWidget(objectName="SubSteps")
        self.sub_layout = QVBoxLayout(self.sub_box)
        self.sub_layout.setContentsMargins(0, 0, 0, 2)
        self.sub_layout.setSpacing(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.sub_box)
        self.set_expanded(False)
        self._show_actions(False)
        self.set_status("pending")

    def _emit_toggled(self, on: bool) -> None:
        self.toggled.emit(self.stage, on)

    def _emit_rerun(self) -> None:
        self.rerun.emit(self.stage)

    def _emit_run_from(self) -> None:
        self.run_from.emit(self.stage)

    def set_status(self, status: str) -> None:
        self.status = status
        _set_state(self.dot, status)
        _set_state(self.name, status)
        if status in ("pending", "cached", "stale", "stopped", "failed"):
            self.summary.setText("" if status == "pending" else status)

    def add_plan(self, steps) -> None:
        for key, label, enabled in steps:
            if key not in self.subs:
                row = SubStepRow(key, label, bool(enabled))
                self.subs[key] = row
                self.sub_layout.addWidget(row)

    def clear_plan(self) -> None:
        for row in self.subs.values():
            row.deleteLater()
        self.subs = {}

    def set_expanded(self, on: bool) -> None:
        self.expanded = on
        self.sub_box.setVisible(on and bool(self.subs))

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        if busy:
            self._show_actions(False)

    def _show_actions(self, on: bool) -> None:
        # the buttons keep their width so the summary does not jump on hover
        self.rerun_btn.setText("↻" if on else "")
        self.from_btn.setText("▶" if on else "")
        self.rerun_btn.setEnabled(on and not self.busy)
        self.from_btn.setEnabled(on and not self.busy)

    def enterEvent(self, event):  # noqa: N802 (Qt API name)
        self._show_actions(not self.busy)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._show_actions(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if self.subs and self.status != "running":
            self.set_expanded(not self.expanded)
        self.clicked.emit(self.stage)
        super().mousePressEvent(event)


class Timeline(QWidget):
    rerun = Signal(str)
    run_from = Signal(str)
    toggled = Signal(str, bool)
    selected = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        layout.addWidget(section("Pipeline"))
        self.rows: dict[str, StageRow] = {}
        for stage in STAGE_ORDER:
            row = StageRow(stage)
            row.rerun.connect(self.rerun)
            row.run_from.connect(self.run_from)
            row.toggled.connect(self.toggled)
            row.clicked.connect(self.selected)
            self.rows[stage] = row
            layout.addWidget(row)

    def reset(self, statuses: dict, enabled: dict) -> None:
        for stage, row in self.rows.items():
            row.clear_plan()
            row.set_expanded(False)
            row.check.blockSignals(True)
            row.check.setChecked(bool(enabled.get(stage)))
            row.check.blockSignals(False)
            row.set_status(statuses.get(stage, "pending"))
        self.update()

    def set_status(self, stage: str, status: str) -> None:
        row = self.rows[stage]
        if status == "running":
            row.clear_plan()
            row.summary.setText("")
        row.set_status(status)
        row.set_expanded(status == "running")
        self.update()

    def add_plan(self, stage: str, steps) -> None:
        row = self.rows[stage]
        row.add_plan(steps)
        row.set_expanded(row.status == "running")

    def set_step(self, stage: str, key: str, state: str, meta: str = "") -> None:
        sub = self.rows[stage].subs.get(key)
        if sub is not None:
            sub.set_state(state, meta if meta or state != "running" else "")
        self._update_badge(stage)

    def current_step(self, stage: str) -> str | None:
        for key, sub in self.rows[stage].subs.items():
            if sub.state in ("running", "waiting"):
                return key
        return None

    def _counts(self, stage: str) -> tuple[int, int]:
        subs = self.rows[stage].subs.values()
        return sum(s.state == "done" for s in subs), sum(s.state != "skipped" for s in subs)

    def _update_badge(self, stage: str) -> None:
        row = self.rows[stage]
        if row.status == "running" and row.subs:
            done, total = self._counts(stage)
            row.summary.setText(f"{done}/{total}")

    def finish(self, stage: str, status: str, compute: float, closed) -> None:
        row = self.rows[stage]
        if closed:
            key, seconds = closed
            state = {"done": "done", "failed": "failed"}.get(status, "pending")
            self.set_step(stage, key, state, f"{seconds:.1f}s" if status == "done" else "")
        row.set_status(status)
        row.set_expanded(False)
        if status == "done":
            done, total = self._counts(stage)
            row.summary.setText(f"{done}/{total} · {compute:.1f}s" if total else f"{compute:.1f}s")
        self.update()

    def set_busy(self, busy: bool) -> None:
        for row in self.rows.values():
            row.set_busy(busy)

    def paintEvent(self, event):  # noqa: N802
        """Vertical rail through the stage dots (git-log style)."""
        rows = list(self.rows.values())
        top = rows[0].dot.mapTo(self, rows[0].dot.rect().center())
        bottom = rows[-1].dot.mapTo(self, rows[-1].dot.rect().center())
        painter = QPainter(self)
        painter.setPen(QPen(QColor(th.current().line), 2))
        painter.drawLine(QPoint(top.x(), top.y()), QPoint(top.x(), bottom.y()))


class InteractionHost(QWidget):
    def __init__(self):
        super().__init__()
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(12, 10, 12, 10)
        self.layout_.setSpacing(6)
        self.layout_.addWidget(section("Interaction"))
        self.idle = _label("Idle", "Muted")
        self.layout_.addWidget(self.idle)
        self.slot = None

    def set_widget(self, widget: QWidget | None) -> None:
        if self.slot is not None:
            self.layout_.removeWidget(self.slot)
            self.slot.deleteLater()
            self.slot = None
        if widget is not None:
            self.slot = widget
            self.layout_.addWidget(widget)
        self.idle.setVisible(widget is None)

    def set_idle(self, text: str) -> None:
        self.set_widget(None)
        self.idle.setText(text)


class LogView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 8)
        layout.setSpacing(4)
        head = QHBoxLayout()
        self.toggle = QToolButton(text="LOG ▸")
        self.toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggle.clicked.connect(self._toggle)
        self.last = _label("", "Meta")
        self.last.setMinimumWidth(10)
        head.addWidget(self.toggle)
        head.addWidget(self.last, 1)
        layout.addLayout(head)
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setMaximumBlockCount(5000)
        self.text.setFixedHeight(180)
        layout.addWidget(self.text)
        self._tail = ""
        self.set_expanded(False)

    def append(self, chunk: str) -> None:
        cursor = self.text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self.text.setTextCursor(cursor)
        self._tail = (self._tail + chunk)[-2000:]
        lines = [ln for ln in self._tail.splitlines() if ln.strip()]
        if lines:
            self.last.setText(lines[-1][:200])

    def _toggle(self) -> None:
        self.set_expanded(not self.text.isVisible())

    def set_expanded(self, on: bool) -> None:
        self.text.setVisible(on)
        self.last.setVisible(not on)
        self.toggle.setText("LOG ▾" if on else "LOG ▸")


SECTION_FOR_STAGE = {"align": "transform", "refine": "refine", "decompose": "decompose",
                     "segment": "segment", "articulate": "articulate", "bind": "bind"}
SECTION_TITLES = {"object": "Object", "pipeline": "Pipeline · run settings (not saved)", "transform": "Align",
                  "refine": "Refine", "decompose": "Decompose", "segment": "Segment",
                  "articulate": "Articulate", "bind": "Bind", "visualization": "Visualization"}
RELOAD_KEYS = {"object_name", "profile", "object_profile"}   # editing these reloads the parameters
NONE_PROFILE = "(none)"


def _parse_null(text: str):
    """Empty -> None; otherwise the YAML value of the text (so `0.5` becomes a float)."""
    return None if not text.strip() else yaml.safe_load(text)


class Collapsible(QWidget):
    """Header button + body; the header shows ● when anything inside was edited."""

    def __init__(self, title: str, level: int = 0):
        super().__init__()
        self.title = title
        self.modified = False
        self.head = QToolButton()
        self.head.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.head.clicked.connect(self._toggle)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(12 if level else 4, 2, 0, 4)
        self.body_layout.setSpacing(3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.head, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.body)
        self.set_expanded(False)

    def _toggle(self) -> None:
        self.set_expanded(self.body.isHidden())

    def set_expanded(self, on: bool) -> None:
        self.body.setVisible(on)
        self._update_head()

    def set_modified(self, on: bool) -> None:
        self.modified = on
        self._update_head()

    def _update_head(self) -> None:
        arrow = "▸" if self.body.isHidden() else "▾"
        self.head.setText(f"{arrow} {self.title}{'  ●' if self.modified else ''}")


class ParamEditor(QWidget):
    """Form generated from the yml values: one collapsible section per stage, widgets by value kind.
    Edits change an in-memory copy; the window snapshots it for the next stage start."""
    changed = Signal()
    object_changed = Signal(dict)
    save_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 6)
        layout.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(section("Parameters"))
        self.badge = _label("", "Modified")
        head.addStretch()
        head.addWidget(self.badge)
        layout.addLayout(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll, 1)
        self.note = _label("Edits apply to the next stage that starts.", "Muted")
        self.note.setVisible(False)
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        self.revert_btn = QPushButton("Revert")
        self.save_btn = QPushButton("Save object profile")
        for b in (self.revert_btn, self.save_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.revert_btn.clicked.connect(self.revert)
        self.save_btn.clicked.connect(self.save_requested)
        buttons.addWidget(self.revert_btn)
        buttons.addStretch()
        buttons.addWidget(self.save_btn)
        layout.addLayout(buttons)
        self.obj, self.params, self._orig = {}, {}, ({}, {})
        self.comments, self.profiles = {}, []
        self.widgets: dict[tuple, QWidget] = {}
        self.sections: dict[str, Collapsible] = {}
        self._meta: dict[QWidget, tuple] = {}   # field widget -> (root, path, kind)

    # --- data ---
    def load(self, obj: dict, params: dict, comments: dict, profiles: list[str]) -> None:
        self.obj, self.params = copy.deepcopy(obj), copy.deepcopy(params)
        self._orig = (copy.deepcopy(obj), copy.deepcopy(params))
        self.comments, self.profiles = comments, profiles
        self._build()

    def values(self) -> tuple[dict, dict]:
        return copy.deepcopy(self.obj), copy.deepcopy(self.params)

    def modified(self) -> bool:
        return (self.obj, self.params) != self._orig

    def revert(self) -> None:
        self.load(*self._orig, self.comments, self.profiles)
        self.changed.emit()

    def after_save(self, obj: dict, profiles: list[str]) -> None:
        self.load(obj, self.params, self.comments, profiles)

    def set_stage_enabled(self, stage: str, on: bool) -> None:
        self.params["pipeline"]["stages"][stage] = bool(on)
        self._mark()
        self.changed.emit()

    def set_busy(self, busy: bool) -> None:
        """While a run is active, object edits (which reload everything) are locked."""
        if "object" in self.sections:
            self.sections["object"].body.setEnabled(not busy)
        self.save_btn.setEnabled(not busy)
        self.revert_btn.setEnabled(not busy)
        self.note.setVisible(busy)

    def show_stage(self, stage: str) -> None:
        key = SECTION_FOR_STAGE.get(stage)
        for name, sec in self.sections.items():
            sec.set_expanded(name == key)
        if key in self.sections:
            self.scroll.ensureWidgetVisible(self.sections[key])

    # --- building ---
    def _build(self) -> None:
        self.widgets, self.sections, self._meta = {}, {}, {}
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(4)

        obj_sec = self._section("object", layout)
        for key in ("object_name", "extension", "profile"):
            self._field(obj_sec, "obj", (key,), self.obj.get(key), self.comments.get(("object", key), ""))
        combo = QComboBox()
        combo.addItems([NONE_PROFILE] + self.profiles)
        combo.setCurrentText(self.obj.get("object_profile") or NONE_PROFILE)
        combo.currentTextChanged.connect(self._on_profile)
        self._row(obj_sec, "object_profile", combo)
        self.widgets[("obj", "object_profile")] = combo

        pipe_sec = self._section("pipeline", layout)
        for key, value in self.params.get("pipeline", {}).items():
            if key != "stages":  # stage switches are the timeline checkboxes
                self._add(pipe_sec, "params", ("pipeline", key), value, 1)
        for name in STAGE_SECTIONS:
            if name not in self.params:
                continue
            sec = self._section(name, layout)
            if name == "segment":
                self._field(sec, "obj", ("parts", "num"), self.obj.get("parts", {}).get("num"), "")
            for key, value in self.params[name].items():
                self._add(sec, "params", (name, key), value, 1)
        layout.addStretch()
        self.scroll.setWidget(content)
        self._mark()

    def _section(self, name: str, layout) -> Collapsible:
        sec = Collapsible(SECTION_TITLES.get(name, name))
        self.sections[name] = sec
        layout.addWidget(sec)
        return sec

    def _add(self, parent: Collapsible, root: str, path: tuple, value, level: int) -> None:
        if isinstance(value, dict):
            group = Collapsible(path[-1], level)
            parent.body_layout.addWidget(group)
            for key, sub in value.items():
                self._add(group, root, path + (key,), sub, level + 1)
        else:
            self._field(parent, root, path, value, self.comments.get(path, ""))

    def _row(self, parent: Collapsible, name: str, widget: QWidget) -> None:
        row = QHBoxLayout()
        label = _label(name)
        label.setToolTip(name)
        label.setMinimumWidth(10)
        row.addWidget(label, 1)
        widget.setFixedWidth(118)
        row.addWidget(widget)
        parent.body_layout.addLayout(row)

    def _field(self, parent: Collapsible, root: str, path: tuple, value, comment: str) -> None:
        kind, choices = field_kind(value, comment)
        if kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(self._on_field)
        elif kind == "int":
            w = QSpinBox()
            w.setRange(-10 ** 9, 10 ** 9)
            w.setValue(int(value))
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self._on_field)
        elif kind == "choice":
            w = QComboBox()
            w.addItems(choices)
            w.setCurrentText(str(value))
            w.currentTextChanged.connect(self._on_field)
        else:
            w = QLineEdit("" if value is None else str(value))
            if kind == "float":
                w.setValidator(QDoubleValidator())
            elif kind == "percent":
                w.setValidator(QRegularExpressionValidator(QRegularExpression(r"^-?\d+(\.\d+)?%$")))
            elif kind == "null":
                w.setPlaceholderText("null")
            w.editingFinished.connect(self._on_field)
        w.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        if comment:
            w.setToolTip(comment.lstrip("# "))
        self._meta[w] = (root, path, kind)
        self.widgets[(root,) + path] = w
        self._row(parent, path[-1], w)

    # --- edits (bound-method slots; the sender identifies the field) ---
    def _on_field(self, *_) -> None:
        w = self.sender()
        root, path, kind = self._meta[w]
        if kind == "bool":
            value = w.isChecked()
        elif kind == "int":
            value = int(w.value())
        elif kind == "choice":
            value = w.currentText()
        else:
            current = self._get(root, path)
            if w.validator() is not None and not w.hasAcceptableInput():
                w.setText("" if current is None else str(current))  # reject invalid text
                return
            try:
                value = {"float": float, "null": _parse_null}.get(kind, str)(w.text())
            except (ValueError, yaml.YAMLError):
                w.setText("" if current is None else str(current))
                return
        self._set(root, path, value)

    def _on_profile(self, text: str) -> None:
        self._set("obj", ("object_profile",), "" if text == NONE_PROFILE else text)

    def _get(self, root: str, path: tuple):
        node = self.obj if root == "obj" else self.params
        for key in path:
            node = node[key]
        return node

    def _set(self, root: str, path: tuple, value) -> None:
        node = self.obj if root == "obj" else self.params
        for key in path[:-1]:
            node = node.setdefault(key, {})
        old = node.get(path[-1])
        if old == value and type(old) is type(value):
            return
        node[path[-1]] = value
        self._mark()
        if root == "obj" and path[0] in RELOAD_KEYS:
            self.object_changed.emit(copy.deepcopy(self.obj))
        else:
            self.changed.emit()

    def _mark(self) -> None:
        orig_obj, orig_params = self._orig
        for name, sec in self.sections.items():
            if name == "object":
                sec.set_modified(self.obj != orig_obj)
            elif name == "segment":
                sec.set_modified(self.params.get(name) != orig_params.get(name)
                                 or self.obj.get("parts") != orig_obj.get("parts"))
            else:
                sec.set_modified(self.params.get(name) != orig_params.get(name))
        self.badge.setText("● modified" if self.modified() else "")
