"""Scenes mounted in the single viewport. A scene is constructed on the worker thread from plain data
only; build() and widget() run on the GUI thread, where every vedo and Qt object is created."""
import sys

import numpy as np
import vedo
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from functions.gui import theme as th
from functions.gui.manip import (KEY_HINTS, AssemblyTarget, VectorGroupTarget, from_fields, key_delta,
                                 to_fields)
from functions.gui.models import (JOINT_STATES, ManualJoints, PartAssignment, cycle_state, group_pairs, picked,
                                  valid_vectors)
from functions.math.geometry import normalize
from functions.visualize.style import arrow_params, label_colors, pastel_hex, state_arrow

VIEW_HINTS = [("Drag", "rotate"), ("Wheel", "zoom"), ("R", "reset view")]


def button(text: str, on_click) -> QPushButton:
    b = QPushButton(text)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keep keyboard focus in the viewport
    b.clicked.connect(lambda _=False: on_click())
    return b


def primary_button(text: str, on_click) -> QPushButton:
    b = button(text, on_click)
    b.setProperty("primary", True)
    return b


def section(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("Section")
    return label


def _column(widget: QWidget) -> QVBoxLayout:
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    return layout


def swatch(color: str, size: int = 10) -> QLabel:
    s = QLabel()
    s.setFixedSize(size, size)
    set_swatch(s, color)
    return s


def set_swatch(s: QLabel, color: str) -> None:
    s.setStyleSheet(f"background: {color}; border-radius: 2px;")


def color_icon(color: str) -> QIcon:
    pix = QPixmap(12, 12)
    pix.fill(QColor(color))
    return QIcon(pix)


def part_legend(parts_num: int) -> QGridLayout:
    """Part k -> its mesh color (pastel_hex, as in label_colors), three per row."""
    grid = QGridLayout()
    grid.setHorizontalSpacing(12)
    for n, p in enumerate(range(1, parts_num + 1)):
        cell = QHBoxLayout()
        cell.setSpacing(4)
        cell.addWidget(swatch(pastel_hex(p)))
        cell.addWidget(QLabel(f"Part {p}"))
        cell.addStretch()
        grid.addLayout(cell, n // 3, n % 3)
    return grid


def fill_joint_list(layout: QVBoxLayout, rows, empty: str) -> None:
    """Refill `layout` with one clickable row per joint. rows: (text, on_click, current, enabled, on_remove);
    `current` highlights the row, and its ✕ stays off while it is being edited."""
    while layout.count():
        old = layout.takeAt(0).widget()
        old.hide()  # deleteLater waits for the event loop
        old.deleteLater()
    if not rows:
        layout.addWidget(QLabel(empty, objectName="Muted"))
    for text, on_click, current, enabled, on_remove in rows:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        b = button(text, on_click)
        b.setCheckable(True)
        b.setChecked(current)
        b.setEnabled(enabled)
        b.setToolTip(text)
        b.setStyleSheet("QPushButton { text-align: left; padding-left: 8px; }")
        h.addWidget(b, 1)
        if on_remove is not None:
            x = button("✕", on_remove)
            x.setEnabled(enabled and not current)
            h.addWidget(x)
        layout.addWidget(row)


class Scene:
    title = ""
    hint = ""
    controls: list = []
    target = None        # Transformable: the viewport attaches the gizmo to it
    move_step = 1.0
    turn_deg = 1.0

    def __init__(self):
        self.viewport = None
        self.finish = None   # set by the window; resolves the waiting worker with result()

    def build(self) -> list:
        return []

    def widget(self) -> QWidget | None:
        return None

    def on_key(self, key: str) -> bool:
        if self.target is None:
            return False
        delta = key_delta(key, self.move_step, self.turn_deg, self.target.pivot())
        if delta is None:
            return False
        self.apply(delta)
        return True

    def apply(self, delta) -> None:
        self.target.apply(delta)
        self.on_change()

    def on_change(self) -> None:
        """Sync panel fields after the target moved."""

    def on_pick(self, actor, button: str) -> bool:
        """True when the click changed the scene (a joint arrow or a fragment)."""
        return False

    def on_enter(self) -> None:
        if self.finish:
            self.finish()

    def on_theme(self) -> None:
        pass

    def result(self):
        return None

    def _render(self) -> None:
        if self.viewport is not None:
            self.viewport.render()

    def _footer(self, label: str = "Done", extra: list | None = None) -> QHBoxLayout:
        row = QHBoxLayout()
        for w in extra or []:
            row.addWidget(w)
        row.addStretch()
        self.primary = primary_button(f"{label} ▸", self.on_enter)
        row.addWidget(self.primary)
        return row


class CheckpointScene(Scene):
    hint = "Debug checkpoint: inspect the result, then Continue."
    controls = VIEW_HINTS + [("Enter", "continue")]

    def __init__(self, title: str, build_fn):
        super().__init__()
        self.title = title
        self._build_fn = build_fn

    def build(self) -> list:
        return list(self._build_fn())

    def widget(self) -> QWidget:
        w = QWidget()
        layout = _column(w)
        msg = QLabel(self.title)
        msg.setWordWrap(True)
        layout.addWidget(msg)
        layout.addLayout(self._footer("Continue"))
        return w


class AlignScene(Scene):
    title = "Align · Manual adjust"
    hint = "Seat the object on the ground plane (z = 0) with Front along +X."
    controls = KEY_HINTS + [("G", "toggle gizmo"), ("R", "reset view"), ("Enter", "done")]
    turn_deg = 1.0

    def __init__(self, verts, faces, point_colors=None, cell_colors=None):
        super().__init__()
        self.verts, self.faces = verts, faces
        self.point_colors, self.cell_colors = point_colors, cell_colors
        size = float(np.ptp(verts, axis=0).max()) if len(verts) else 1.0
        self.size = size if np.isfinite(size) and size > 0 else 1.0
        self.move_step = self.size * 0.02
        self.target = AssemblyTarget(on_change=self._move_mesh)
        self.fields = {}
        self._syncing = False

    def _move_mesh(self, delta) -> None:
        self.mesh.apply_transform(vedo.LinearTransform(delta))

    def build(self) -> list:
        t = th.current()
        self.mesh = vedo.Mesh([self.verts, self.faces]).alpha(0.6).pickable(False)
        if self.point_colors is not None:
            self.mesh.pointcolors = self.point_colors
        elif self.cell_colors is not None:
            self.mesh.cellcolors = self.cell_colors
        else:
            self.mesh.c(t.mesh)
        length = self.size * 0.8
        axes = [vedo.Line((0, 0, 0), tuple(np.eye(3)[i] * length), c=c, lw=3)
                for i, c in enumerate((t.axis_x, t.axis_y, t.axis_z))]
        grid = vedo.Grid(pos=(0, 0, 0), s=(self.size * 1.2, self.size * 1.2)).c(t.text3).alpha(0.15)
        self.static = axes + [grid]
        return [self.mesh, *self.static]

    def widget(self) -> QWidget:
        w = QWidget()
        layout = _column(w)
        grid = QGridLayout()
        for j, axis in enumerate("XYZ"):
            grid.addWidget(QLabel(axis), 0, j + 1, alignment=Qt.AlignmentFlag.AlignCenter)
        for row, (name, limit, decimals, suffix) in enumerate(
                (("Rotate", 180.0, 1, "°"), ("Move", self.size * 10, 4, ""))):
            grid.addWidget(QLabel(name), row + 1, 0)
            for j in range(3):
                box = QDoubleSpinBox()
                box.setRange(-limit, limit)
                box.setDecimals(decimals)
                box.setSuffix(suffix)
                box.setKeyboardTracking(False)
                box.valueChanged.connect(self._fields_changed)
                self.fields[(name, j)] = box
                grid.addWidget(box, row + 1, j + 1)
        layout.addLayout(grid)

        steps = QHBoxLayout()
        steps.addWidget(QLabel("Step"))
        move_box, turn_box = QDoubleSpinBox(), QDoubleSpinBox()
        move_box.setDecimals(4)
        move_box.setRange(1e-6, self.size)
        move_box.setValue(self.move_step)
        move_box.valueChanged.connect(lambda v: setattr(self, "move_step", v))
        turn_box.setRange(0.1, 45.0)
        turn_box.setSuffix("°")
        turn_box.setValue(self.turn_deg)
        turn_box.valueChanged.connect(lambda v: setattr(self, "turn_deg", v))
        steps.addWidget(move_box)
        steps.addWidget(turn_box)
        layout.addLayout(steps)
        layout.addLayout(self._footer(extra=[button("Reset", self._reset)]))
        self.on_change()
        return w

    def _reset(self) -> None:
        self.target.set_matrix(np.eye(4))
        self.on_change()
        self._render()

    def _fields_changed(self, *_) -> None:
        if self._syncing:
            return
        euler = [self.fields[("Rotate", j)].value() for j in range(3)]
        trans = [self.fields[("Move", j)].value() for j in range(3)]
        self.target.set_matrix(from_fields(euler, trans))
        self._render()

    def on_change(self) -> None:
        if not self.fields:
            return
        euler, trans = to_fields(self.target.matrix)
        self._syncing = True
        for j in range(3):
            self.fields[("Rotate", j)].setValue(float(euler[j]))
            self.fields[("Move", j)].setValue(float(trans[j]))
        self._syncing = False

    def on_theme(self) -> None:
        if self.point_colors is None and self.cell_colors is None:
            self.mesh.c(th.current().mesh)

    def result(self):
        return self.target.matrix.copy()


class PartSelectScene(Scene):
    title = "Segment · Part selection"
    hint = "Choose a part, then click fragments to assign them."
    controls = [("Left click", "assign"), ("Right click", "revert"), ("Tab", "next part")] + VIEW_HINTS[2:] + \
        [("Enter", "done")]

    def __init__(self, fragments, verts, faces, parts_num: int):
        super().__init__()
        self.fragments = fragments
        self.verts, self.faces = verts, faces
        self.model = PartAssignment(len(fragments), parts_num)
        self.chips = []
        self.meshes = []

    def build(self) -> list:
        base = vedo.Mesh([self.verts, self.faces]).c(th.current().none).alpha(0.08).pickable(False)
        self.meshes = [vedo.Mesh([v, f]) for v, f in self.fragments]
        self.index = {m.actor: i for i, m in enumerate(self.meshes, start=1)}
        self._recolor()
        return [base, *self.meshes]

    def _recolor(self) -> None:
        t, mode = th.current(), self.model.mode
        for i, m in enumerate(self.meshes, start=1):
            owner = self.model.owner[i]
            if mode == 0:
                m.c(pastel_hex(owner)).alpha(0.75)
            elif owner == mode:
                m.c(pastel_hex(mode)).alpha(0.95)
            else:
                m.c(t.none).alpha(0.2)

    def _refresh(self) -> None:
        self._recolor()
        self._update_chips()
        self._render()

    def on_pick(self, actor, button: str) -> bool:
        i = self.index.get(actor)
        if i is None:
            return False
        changed = self.model.assign(i) if button == "left" else self.model.undo(i)
        if changed:
            self._refresh()
        return changed

    def on_key(self, key: str) -> bool:
        if key == "tab":
            self.model.cycle_mode()
            self._refresh()
            return True
        return False

    def _set_mode(self, mode: int) -> None:
        self.model.set_mode(mode)
        self._refresh()

    def widget(self) -> QWidget:
        w = QWidget()
        layout = _column(w)
        layout.addWidget(section("Active part"))
        grid = QGridLayout()
        self.chips = []
        for mode in range(self.model.parts_num + 1):
            chip = button("", lambda m=mode: self._set_mode(m))
            chip.setCheckable(True)
            if mode:
                chip.setStyleSheet(f"QPushButton {{ border-left: 6px solid {pastel_hex(mode)}; }}")
            self.chips.append(chip)
            grid.addWidget(chip, mode // 3, mode % 3)
        layout.addLayout(grid)
        layout.addLayout(self._footer())
        self._update_chips()
        return w

    def _update_chips(self) -> None:
        counts = self.model.counts()
        for mode, chip in enumerate(self.chips):
            chip.setChecked(mode == self.model.mode)
            chip.setText("View" if mode == 0 else f"Part {mode} · {counts[mode]}")

    def on_theme(self) -> None:
        self._recolor()

    def result(self):
        return list(self.model.owner)


class JointSelectScene(Scene):
    hint = "Click arrows: None → Revolute → Prismatic. Keys and gizmo move every vector of this pair."
    controls = [("Click arrow", "cycle type")] + KEY_HINTS + [("G", "toggle gizmo"), ("R", "reset view"),
                                                             ("Enter", "next pair / done")]
    turn_deg = 1.5

    def __init__(self, bicons, verts, faces, vert_label):
        super().__init__()
        self.verts, self.faces, self.vert_label = verts, faces, vert_label
        self.pairs = group_pairs(bicons)
        self.items = [valid_vectors(group) for _, group in self.pairs]
        self.counters = [[0] for _ in self.pairs]
        self.size = arrow_params(verts, scale=0.8)
        diag = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
        self.move_step = diag * 0.02 if np.isfinite(diag) and diag > 0 else 1.0
        self.i = 0
        self.arrows = {}        # vtkActor -> vector dict
        self.arrow_objs = []
        self.pair_label = self.counts_label = self.list_box = None
        self._select_pair(0)

    def _select_pair(self, i: int) -> None:
        self.i = i
        if not self.pairs:
            self.title, self.target = "Articulate · No part pairs", None
            return
        (p, q), _ = self.pairs[i]
        self.title = f"Articulate · Parts {p} ↔ {q} ({i + 1}/{len(self.pairs)})"
        self.target = VectorGroupTarget([v for _, v in self.items[i]], on_change=lambda d: self._redraw_arrows())

    def build(self) -> list:
        if not self.pairs:
            return [vedo.Mesh([self.verts, self.faces]).c(th.current().none).alpha(0.3).pickable(False)]
        (p, q), _ = self.pairs[self.i]
        mesh = vedo.Mesh([self.verts, self.faces])
        mesh.pointcolors = label_colors(self.vert_label, keep=(p, q))
        mesh.alpha(0.4).pickable(False)
        return [mesh, *self._make_arrows()]

    def _make_arrows(self) -> list:
        self.arrows, self.arrow_objs = {}, []
        for _, v in (self.items[self.i] if self.pairs else []):
            arrow = state_arrow(np.asarray(v["center"], dtype=float), normalize(v["n"]),
                                v.get("state", "None"), self.size)
            self.arrows[arrow.actor] = v
            self.arrow_objs.append(arrow)
        return self.arrow_objs

    def _redraw_arrows(self) -> None:
        if self.viewport is None:
            return
        if self.arrow_objs:
            self.viewport.plt.remove(*self.arrow_objs)
        self.viewport.plt.add(*self._make_arrows())
        self._update_labels()

    def on_pick(self, actor, button: str) -> bool:
        v = self.arrows.get(actor)
        if v is None or button != "left":
            return False
        cycle_state(v, self.counters[self.i])
        self._redraw_arrows()
        self._update_list()
        self._render()
        return True

    def _go(self, step: int) -> None:
        if self.pairs:
            self._goto((self.i + step) % len(self.pairs))

    def _goto(self, i: int) -> None:
        if not self.pairs or self.viewport is None:
            return
        self._select_pair(i)
        self.viewport.set_actors(self.build())
        self.viewport.gizmo.attach(self.target)
        self.viewport.refresh_overlays()
        self._update_labels()
        self._update_list()
        self._render()

    def on_enter(self) -> None:
        if self.pairs and self.i < len(self.pairs) - 1:
            self._go(+1)
        elif self.finish:
            self.finish()

    def widget(self) -> QWidget:
        w = QWidget()
        layout = _column(w)
        layout.addWidget(section("Part pair"))
        self.pair_label = QLabel()
        self.counts_label = QLabel()
        self.counts_label.setObjectName("Muted")
        pair_row = QHBoxLayout()
        pair_row.setSpacing(4)
        self.pair_swatches = (swatch(th.current().none), swatch(th.current().none))  # the pair's part colors
        for s in self.pair_swatches:
            pair_row.addWidget(s)
        pair_row.addSpacing(4)
        pair_row.addWidget(self.pair_label, 1)
        layout.addLayout(pair_row)
        layout.addWidget(self.counts_label)
        legend = QHBoxLayout()
        t = th.current()
        for name, color in (("Revolute", t.revolute), ("Prismatic", t.prismatic), ("None", t.none)):
            legend.addWidget(swatch(color))
            legend.addWidget(QLabel(name))
        legend.addStretch()
        layout.addLayout(legend)
        layout.addWidget(section("Joints"))
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(4)
        layout.addLayout(self.list_box)
        footer = QHBoxLayout()
        footer.addStretch()
        self.prev_btn = button("◂ Prev pair", lambda: self._goto(self.i - 1) if self.i > 0 else None)
        footer.addWidget(self.prev_btn)
        self.primary = primary_button("Next pair ▸", self.on_enter)
        footer.addWidget(self.primary)
        layout.addLayout(footer)
        self._update_labels()
        self._update_list()
        return w

    def _update_list(self) -> None:
        """Every pair with a selected vector; clicking one jumps back to that pair."""
        if self.list_box is None:
            return
        rows = []
        for idx, ((p, q), _) in enumerate(self.pairs):
            states = [v["state"] for v in picked([v for _, v in self.items[idx]])]
            if states:
                kinds = ", ".join(f"{k} ×{states.count(k)}" for k in JOINT_STATES if k in states)
                rows.append((f"Parts {p} ↔ {q} · {kinds}", lambda idx=idx: self._goto(idx), idx == self.i, True, None))
        fill_joint_list(self.list_box, rows, "No joints selected yet.")

    def _update_labels(self) -> None:
        if self.pair_label is None:
            return
        if not self.pairs:
            self.pair_label.setText("No part pairs to review.")
            self.counts_label.setText("")
            self.primary.setText("Done ▸")
            self.prev_btn.setEnabled(False)
            return
        (p, q), _ = self.pairs[self.i]
        states = [v.get("state", "None") for _, v in self.items[self.i]]
        for s, part in zip(self.pair_swatches, (p, q)):
            set_swatch(s, pastel_hex(part))
        self.pair_label.setText(f"Parts {p} ↔ {q} · {self.i + 1} / {len(self.pairs)}")
        self.counts_label.setText(f"Revolute {states.count('Revolute')} · Prismatic {states.count('Prismatic')}"
                                  f" · {len(states)} candidates")
        self.primary.setText("Done ▸" if self.i == len(self.pairs) - 1 else "Next pair ▸")
        self.prev_btn.setEnabled(self.i > 0)  # the first pair has no previous one (no wrap-around)

    def on_theme(self) -> None:
        self._redraw_arrows()


class ManualJointScene(Scene):
    """User study condition A: no suggestions. One X/Y/Z triad at a time starts at the world origin; keys
    and the gizmo move it as a whole, clicks set each arrow's type, and Confirm stores it for the chosen
    parent/child pair. Clicking a confirmed joint in the list brings its triad back for editing."""
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
        for i, joint in enumerate(self.model.confirmed):
            if i == self.model.editing:  # shown as the active triad instead
                continue
            for v in picked(joint["triad"]):
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

    def _edit(self, i: int) -> None:
        if self.model.edit(i):
            self._sync_boxes()
            self._recolor()
            self._attach(VectorGroupTarget(self.model.triad, on_change=lambda d: self._redraw()))
        else:
            self._update_panel()  # undo the row's own check toggle

    def _cancel(self) -> None:
        if self.model.triad is not None:
            self.model.cancel()
            self._attach(None)

    def _remove(self, i: int) -> None:
        if self.model.remove(i):
            self._changed()

    def _sync_boxes(self) -> None:
        for key, box in self.boxes.items():
            box.blockSignals(True)
            box.setCurrentIndex(getattr(self.model, key) - 1)
            box.blockSignals(False)
            set_swatch(self.box_swatches[key], pastel_hex(getattr(self.model, key)))

    def _set_pair(self, *_) -> None:
        self.model.parent = self.boxes["parent"].currentData()
        self.model.child = self.boxes["child"].currentData()
        for key, s in self.box_swatches.items():
            set_swatch(s, pastel_hex(getattr(self.model, key)))
        self._recolor()
        self._update_panel()
        self._render()

    def _done(self) -> None:
        if self.finish:
            self.finish()

    def widget(self) -> QWidget:
        w = QWidget()
        layout = _column(w)
        layout.addWidget(section("Parts"))
        layout.addLayout(part_legend(self.model.parts_num))
        note = QLabel("The viewport colors only the parent and child; other parts are gray.", objectName="Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(section("Part pair"))
        grid = QGridLayout()
        self.box_swatches = {}
        for row, key in enumerate(("parent", "child")):
            box = QComboBox()
            box.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keep keyboard focus in the viewport
            for p in range(1, self.model.parts_num + 1):
                box.addItem(color_icon(pastel_hex(p)), f"Part {p}", p)
            box.setCurrentIndex(getattr(self.model, key) - 1)
            box.currentIndexChanged.connect(self._set_pair)
            self.boxes[key] = box
            self.box_swatches[key] = swatch(pastel_hex(getattr(self.model, key)), 12)
            grid.addWidget(QLabel(key.capitalize()), row, 0)
            grid.addWidget(self.box_swatches[key], row, 1)
            grid.addWidget(box, row, 2)
        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)
        row = QHBoxLayout()
        self.new_btn = button("+ New joint", self._new)
        self.confirm_btn = button("Confirm joint", self._confirm)
        self.cancel_btn = button("Cancel", self._cancel)
        for b in (self.new_btn, self.confirm_btn, self.cancel_btn):
            row.addWidget(b)
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
        m = self.model
        self.new_btn.setEnabled(m.can_add())
        self.confirm_btn.setEnabled(m.can_confirm())
        self.confirm_btn.setText("Confirm joint" if m.editing is None else "Update joint")
        self.cancel_btn.setEnabled(m.triad is not None)
        idle = m.triad is None
        fill_joint_list(self.list_box, [(ManualJoints.describe(j), lambda i=i: self._edit(i), i == m.editing,
                                         idle or i == m.editing, lambda i=i: self._remove(i))
                                        for i, j in enumerate(m.confirmed)], "No joints yet.")

    def on_theme(self) -> None:
        self._redraw()

    def result(self):
        return {"bicons": self.model.bicons(),
                "manual_pairs": [{"parent": j["parent"], "child": j["child"]} for j in self.model.confirmed]}


if __name__ == "__main__":
    # Manual check: `.venv/bin/python -m functions.gui.scenes align|parts|joints|manual [--smoke]`
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QSplitter

    from functions.gui.viewport import Viewport

    box = vedo.Box(size=(2, 1, 1)).triangulate()
    verts, faces = np.asarray(box.vertices, dtype=float), np.asarray(box.cells, dtype=np.int64)
    kind = sys.argv[1] if len(sys.argv) > 1 else "align"
    if kind == "parts":
        halves = [vedo.Box(pos=(x, 0, 0), size=(1, 1, 1)).triangulate() for x in (-0.5, 0.5)]
        scene = PartSelectScene([(np.asarray(h.vertices), np.asarray(h.cells)) for h in halves], verts, faces, 2)
    elif kind == "joints":
        label = np.where(verts[:, 0] < 0, 1, 2)
        bicons = [{"a": {"src": 1, "dst": 2}, "center": [0, 0, 0],
                   "vectors": [{"n": [0, 0, 1], "center": [0, 0, 0.5]}, {"n": [0, 1, 0]}]},
                  {"a": {"src": 2, "dst": 3}, "center": [1, 0, 0], "vectors": [{"n": [1, 0, 0]}]}]
        scene = JointSelectScene(bicons, verts, faces, label)
    elif kind == "manual":
        scene = ManualJointScene(verts, faces, np.where(verts[:, 0] < 0, 1, 2), 2)
    else:
        scene = AlignScene(verts, faces)

    app = QApplication(sys.argv[:1])
    app.setStyleSheet(th.stylesheet(th.current()))
    split = QSplitter()
    view = Viewport()
    split.addWidget(view)
    view.mount(scene)
    split.addWidget(scene.widget() or QWidget())
    split.resize(1600, 900)
    split.setSizes([1248, 352])
    scene.finish = lambda: (print("result:", scene.result()), app.quit())
    split.show()
    if "--smoke" in sys.argv:
        QTimer.singleShot(1500, app.quit)
    app.exec()
    view.close_vtk()
