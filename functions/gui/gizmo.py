"""3D transform gizmo: drag an axis arrow to translate along it, drag a ring to rotate about it.
Drawn in an always-on-top overlay renderer that copies the main camera, kept at a constant on-screen
size, and bound to any Transformable (functions.gui.manip)."""
import math

import numpy as np
import vedo
from vtkmodules.vtkRenderingCore import vtkCellPicker, vtkRenderer

from functions.gui import theme as th
from functions.gui.manip import rotation, translation

SCREEN_FRACTION = 0.16  # arrow length relative to the visible height at the pivot


def axis_drag_distance(d, p_scr, q_scr, length: float) -> float:
    """World distance along an axis for a mouse move `d` (pixels); the axis segment of world `length`
    is drawn on screen from `p_scr` to `q_scr`."""
    s = np.asarray(q_scr, dtype=float) - np.asarray(p_scr, dtype=float)
    n = np.linalg.norm(s)
    if n < 1e-6:
        return 0.0
    return float(np.dot(np.asarray(d, dtype=float), s / n)) * length / n


def ring_drag_angle(m0, m1, c) -> float:
    """Signed screen angle in degrees (counter-clockwise positive) swept from m0 to m1 around c."""
    a = np.asarray(m0, dtype=float) - c
    b = np.asarray(m1, dtype=float) - c
    if np.linalg.norm(a) < 2 or np.linalg.norm(b) < 2:
        return 0.0
    return math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], float(a @ b)))


def world_to_display(renderer, p) -> np.ndarray:
    renderer.SetWorldPoint(float(p[0]), float(p[1]), float(p[2]), 1.0)
    renderer.WorldToDisplay()
    x, y, _ = renderer.GetDisplayPoint()
    return np.array([x, y])


class TransformGizmo:
    def __init__(self, main_renderer, render_window, on_delta, request_render):
        self.main, self.on_delta, self.request_render = main_renderer, on_delta, request_render
        self.ren = vtkRenderer()
        self.ren.SetLayer(1)
        self.ren.InteractiveOff()
        render_window.SetNumberOfLayers(max(2, render_window.GetNumberOfLayers()))
        render_window.AddRenderer(self.ren)
        self.picker = vtkCellPicker()
        self.picker.SetTolerance(0.004)
        self.picker.PickFromListOn()
        self.handles = {}       # vtkActor -> (kind, axis index, vedo object)
        self.target = None
        self.visible = True
        self.drag = None        # (kind, axis index, last mouse position)
        self.hover = None
        self.scale = 1.0
        for i in range(3):
            axis = np.eye(3)[i]
            arrow = vedo.Arrow((0, 0, 0), tuple(axis), shaft_radius=0.025, head_radius=0.07, head_length=0.22)
            ring = vedo.Torus(r1=0.72, r2=0.016)
            if i == 0:
                ring.rotate_y(90)
            elif i == 1:
                ring.rotate_x(90)
            for obj, kind in ((arrow, "move"), (ring, "turn")):
                obj.lighting("off").pickable(True)
                self.handles[obj.actor] = (kind, i, obj)
                self.ren.AddActor(obj.actor)
                self.picker.AddPickList(obj.actor)
        self.set_theme(th.current())
        self._update_visibility()
        main_renderer.AddObserver("StartEvent", self.sync)

    def _color(self, i: int) -> str:
        t = th.current()
        return (t.axis_x, t.axis_y, t.axis_z)[i]

    def set_theme(self, t) -> None:
        for kind, i, obj in self.handles.values():
            obj.c(self._color(i))

    def _update_visibility(self) -> None:
        on = self.visible and self.target is not None
        for actor in self.handles:
            actor.SetVisibility(on)

    def attach(self, target) -> None:
        self.target = target
        self.drag = None
        self._update_visibility()

    def detach(self) -> None:
        self.attach(None)

    def toggle(self) -> None:
        self.visible = not self.visible
        self._update_visibility()

    def sync(self, *_) -> None:
        """Copy the main camera and keep the gizmo on the pivot at a constant on-screen size."""
        cam, c = self.main.GetActiveCamera(), self.ren.GetActiveCamera()
        c.SetPosition(cam.GetPosition())
        c.SetFocalPoint(cam.GetFocalPoint())
        c.SetViewUp(cam.GetViewUp())
        c.SetViewAngle(cam.GetViewAngle())
        c.SetParallelProjection(cam.GetParallelProjection())
        c.SetParallelScale(cam.GetParallelScale())
        if self.target is None:
            return
        p = self.target.pivot()
        if cam.GetParallelProjection():
            visible_h = 2 * cam.GetParallelScale()
        else:
            dist = np.linalg.norm(np.array(cam.GetPosition()) - p)
            visible_h = 2 * dist * math.tan(math.radians(cam.GetViewAngle()) / 2)
        self.scale = max(visible_h * SCREEN_FRACTION, 1e-9)
        for actor in self.handles:
            actor.SetPosition(*p)
            actor.SetScale(self.scale)
        self.ren.ResetCameraClippingRange()

    def _pick(self, x, y):
        if self.target is None or not self.visible:
            return None
        if not self.picker.Pick(x, y, 0, self.ren):
            return None
        return self.handles.get(self.picker.GetActor())

    def _set_hover(self, handle) -> None:
        if handle is self.hover:
            return
        if self.hover is not None:
            self.hover[2].c(self._color(self.hover[1]))
        if handle is not None:
            handle[2].c(th.current().hover)
        self.hover = handle
        self.request_render()

    def on_press(self, x, y) -> bool:
        handle = self._pick(x, y)
        if handle is None:
            return False
        self.drag = (handle[0], handle[1], np.array([x, y], dtype=float))
        return True

    def on_move(self, x, y) -> bool:
        if self.drag is None:
            self._set_hover(self._pick(x, y))
            return False
        kind, i, last = self.drag
        cur = np.array([x, y], dtype=float)
        p = self.target.pivot()
        axis = np.eye(3)[i]
        if kind == "move":
            dist = axis_drag_distance(cur - last, world_to_display(self.main, p),
                                      world_to_display(self.main, p + axis * self.scale), self.scale)
            delta = translation(axis * dist)
        else:
            angle = ring_drag_angle(last, cur, world_to_display(self.main, p))
            toward = np.dot(axis, np.array(self.main.GetActiveCamera().GetPosition()) - p) > 0
            delta = rotation(axis, angle if toward else -angle, p)
        self.drag = (kind, i, cur)
        self.on_delta(delta)
        return True

    def on_release(self) -> bool:
        was_dragging = self.drag is not None
        self.drag = None
        return was_dragging
