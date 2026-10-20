"""Side panel widgets: git-log style stage timeline, interaction host, parameter editor, and log."""
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QToolButton, QVBoxLayout,
                               QWidget)

from functions.gui import theme as th
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
        self.check.toggled.connect(lambda on: self.toggled.emit(self.stage, on))
        self.dot = _label(name="Dot")
        self.name = _label(STAGE_LABELS[stage], "StageName")
        self.summary = _label("", "Meta")
        self.rerun_btn = QToolButton(toolTip="Re-run this stage")
        self.from_btn = QToolButton(toolTip="Run from this stage")
        for b in (self.rerun_btn, self.from_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setFixedWidth(20)
        self.rerun_btn.clicked.connect(lambda: self.rerun.emit(self.stage))
        self.from_btn.clicked.connect(lambda: self.run_from.emit(self.stage))

        header = QHBoxLayout()
        header.setContentsMargins(0, 2, 0, 2)
        header.setSpacing(8)
        for w in (self.check, self.dot, self.name):
            header.addWidget(w)
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
        self.toggle.clicked.connect(lambda: self.set_expanded(not self.text.isVisible()))
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

    def set_expanded(self, on: bool) -> None:
        self.text.setVisible(on)
        self.last.setVisible(not on)
        self.toggle.setText("LOG ▾" if on else "LOG ▸")
