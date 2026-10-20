"""The single 3D viewport: one vedo.Plotter embedded in Qt, scene mounting, text overlays, the view
cube, the transform gizmo, and one mouse/key router (view cube -> gizmo -> scene -> camera)."""
import sys

import vtkmodules.qt

vtkmodules.qt.PyQtImpl = "PySide6"  # must be set before importing QVTKRenderWindowInteractor
vtkmodules.qt.QVTKRWIBase = "QOpenGLWidget"  # the default QWidget base hangs the event loop on macOS

import vedo  # noqa: E402
from PySide6.QtWidgets import QVBoxLayout, QWidget  # noqa: E402
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor  # noqa: E402
from vtkmodules.vtkRenderingCore import vtkPropPicker  # noqa: E402

from functions.gui import theme as th  # noqa: E402
from functions.gui.gizmo import TransformGizmo  # noqa: E402
from functions.gui.viewcube import HOME, ViewCube  # noqa: E402

KEY_NAMES = {"Tab": "tab", "ISO_Left_Tab": "tab", "Return": "enter", "KP_Enter": "enter",
             "space": "space", "Escape": "escape"}
HINTS_PER_ROW = 4
# VTK's built-in overlay fonts have no glyphs for these; the Qt panel keeps the originals
OVERLAY_ASCII = str.maketrans({"↔": "<->", "→": "->", "◂": "<", "▸": ">"})


class _VTKWidget(QVTKRenderWindowInteractor):
    """Keeps Tab inside the viewport instead of moving Qt focus."""

    def focusNextPrevChild(self, next):  # noqa: N802 (Qt API name)
        return False


class Viewport(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.vtk = _VTKWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.vtk)

        self.plt = vedo.Plotter(qt_widget=self.vtk, axes=0)
        self.plt.show()
        self.renderer = self.plt.renderer
        self.iren = self.plt.interactor
        for ev in ("KeyPressEvent", "KeyReleaseEvent", "CharEvent"):  # drop VTK/vedo default key bindings
            self.iren.RemoveObservers(ev)

        dpr = self.devicePixelRatioF()
        self.cube = ViewCube(self.renderer, self.plt.window, self.render, dpr)
        self.gizmo = TransformGizmo(self.renderer, self.plt.window, self._on_gizmo_delta, self.render)
        self.scene = None
        self.actors = []
        self.overlays = []
        self._picker = vtkPropPicker()
        self._tags = {}
        for ev, fn in (("LeftButtonPressEvent", self._left_press), ("LeftButtonReleaseEvent", self._left_release),
                       ("RightButtonPressEvent", self._right_press), ("MouseMoveEvent", self._move),
                       ("KeyPressEvent", self._key)):
            self._tags[ev] = self.iren.AddObserver(ev, fn, 10.0)
        self.cube.set_view(HOME)  # start in the same isometric view R returns to
        self.apply_theme(th.current())

    # --- event routing ---
    def _swallow(self, ev: str) -> None:
        """Stop lower-priority observers (the camera interactor style) from seeing this event."""
        self.iren.GetCommand(self._tags[ev]).SetAbortFlag(1)

    def _left_press(self, obj, ev):
        x, y = self.iren.GetEventPosition()
        if self.cube.on_press(x, y) or self.gizmo.on_press(x, y):
            self._swallow(ev)
            return
        self._pick(x, y, "left")

    def _left_release(self, obj, ev):
        if self.gizmo.on_release():
            self._swallow(ev)

    def _right_press(self, obj, ev):
        x, y = self.iren.GetEventPosition()
        if self.cube.contains(x, y):
            self._swallow(ev)
            return
        self._pick(x, y, "right")

    def _move(self, obj, ev):
        x, y = self.iren.GetEventPosition()
        if self.gizmo.on_move(x, y):
            self._swallow(ev)
            return
        self.cube.on_move(x, y)

    def _pick(self, x, y, button: str) -> None:
        if self.scene is not None and self._picker.Pick(x, y, 0, self.renderer):
            self.scene.on_pick(self._picker.GetActor(), button)

    def _key(self, obj, ev):
        sym = self.iren.GetKeySym() or ""
        key = KEY_NAMES.get(sym, sym.lower())
        if key == "r":
            self.reset_view()
        elif key == "g":
            self.gizmo.toggle()
            self.render()
        elif key == "enter":
            if self.scene is not None:
                self.scene.on_enter()
        elif self.scene is not None and self.scene.on_key(key):
            self.render()

    def _on_gizmo_delta(self, delta) -> None:
        if self.scene is not None:
            self.scene.apply(delta)
            self.render()

    # --- scene lifecycle ---
    def mount(self, scene) -> None:
        self.scene = scene
        scene.viewport = self
        self.set_actors(scene.build())
        target = getattr(scene, "target", None)
        self.gizmo.attach(target)
        self.refresh_overlays()
        self.suspend(False)
        self.reset_view()
        self.vtk.setFocus()

    def unmount(self) -> None:
        """Detach the scene; its actors stay as the last frame until the next mount."""
        self.scene = None
        self.gizmo.detach()
        self.refresh_overlays()
        self.render()

    def set_actors(self, actors) -> None:
        self.plt.clear()
        self.actors = list(actors)
        self.plt.add(*self.actors, *self.overlays)
        self.render()

    def refresh_overlays(self) -> None:
        if self.overlays:
            self.plt.remove(*self.overlays)
        t, s = th.current(), self.scene
        self.overlays = []
        if s is not None and s.title:
            text = (f"{s.title}\n{s.hint}" if s.hint else s.title).translate(OVERLAY_ASCII)
            self.overlays.append(vedo.Text2D(text, pos="top-left", s=0.85, c=t.text, bg=t.panel,
                                             alpha=0.85, font="Arial"))
        if s is not None and s.controls:
            items = [f"{k}  {v}" for k, v in s.controls]
            rows = ["     ".join(items[i:i + HINTS_PER_ROW]) for i in range(0, len(items), HINTS_PER_ROW)]
            self.overlays.append(vedo.Text2D("\n".join(rows).translate(OVERLAY_ASCII), pos="bottom-left", s=0.75, c=t.text2,
                                             bg=t.panel, alpha=0.85, font="Arial"))
        if self.overlays:
            self.plt.add(*self.overlays)

    # --- view ---
    def render(self) -> None:
        self.plt.render()

    def reset_view(self) -> None:
        """Isometric Front-Right-Top view fitted to the scene."""
        self.cube.set_view(HOME)
        self.renderer.ResetCamera()
        self.render()

    def suspend(self, on: bool) -> None:
        """Minimal mode: ignore input (and the renders it triggers) while stages compute."""
        self.vtk.setEnabled(not on)

    def apply_theme(self, t) -> None:
        self.plt.background(t.vp_bottom, t.vp_top)
        self.cube.set_theme(t)
        self.gizmo.set_theme(t)
        if self.scene is not None:
            self.scene.on_theme()
        self.refresh_overlays()
        self.render()

    def close_vtk(self) -> None:
        self.vtk.Finalize()


if __name__ == "__main__":
    # Manual check: `.venv/bin/python -m functions.gui.viewport` (add --smoke to auto-quit after 1.5 s)
    import numpy as np
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from functions.gui.manip import AssemblyTarget

    class _DemoScene:
        title = "Viewport demo"
        hint = "Drag gizmo arrows/rings; click the cube; R resets, G toggles the gizmo."
        controls = [("Drag", "rotate"), ("Wheel", "zoom"), ("R", "reset view"), ("G", "gizmo")]
        viewport = None

        def __init__(self):
            self.target = AssemblyTarget(on_change=lambda d: self.mesh.apply_transform(vedo.LinearTransform(d)))

        def build(self):
            self.mesh = vedo.Cube(side=1.0).c(th.current().mesh).alpha(0.8)
            return [self.mesh, vedo.Grid(s=(4, 4)).c(th.current().text3).alpha(0.2)]

        def apply(self, delta):
            self.target.apply(delta)

        def on_key(self, key):
            return False

        def on_pick(self, actor, button):
            print(f"pick {button}: {actor is self.mesh.actor}")

        def on_enter(self):
            print("enter; matrix:\n", np.round(self.target.matrix, 3))

        def on_theme(self):
            self.mesh.c(th.current().mesh)

    app = QApplication(sys.argv[:1])
    app.setStyleSheet(th.stylesheet(th.current()))
    view = Viewport()
    view.resize(1280, 720)
    view.show()
    view.mount(_DemoScene())
    if "--smoke" in sys.argv:
        QTimer.singleShot(1500, app.quit)
    app.exec()
    view.close_vtk()
