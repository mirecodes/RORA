"""Corner navigation cube. Clicking a face looks straight at it, an edge looks at its two faces at 45°,
a corner gives the isometric view of its three faces. Z is up and Front is +X (URDF); side labels
follow the viewer as in CAD cubes (looking at Front, +Y is Right)."""
import numpy as np
from PySide6.QtCore import QTimer
from vtkmodules.vtkFiltersSources import vtkCubeSource
from vtkmodules.vtkRenderingAnnotation import vtkAnnotatedCubeActor
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper, vtkRenderer

from functions.gui import theme as th

FACES = {(1, 0, 0): "Front", (-1, 0, 0): "Back", (0, 1, 0): "Right", (0, -1, 0): "Left",
         (0, 0, 1): "Top", (0, 0, -1): "Bottom"}
HOME = (1, 1, 1)   # Front-Right-Top corner
SIZE_PX = 110      # cube viewport edge in logical pixels
BAND = 0.6         # |coordinate| / half-size above this counts as touching that face


def piece_at(point, half: float = 0.5, band: float = BAND):
    """Cube piece under a surface point: one non-zero entry = face, two = edge, three = corner."""
    p = np.asarray(point, dtype=float) / half
    piece = tuple(int(np.sign(c)) if abs(c) > band else 0 for c in p)
    return piece if any(piece) else None


def ray_box(origin, direction, half: float = 0.5):
    """Nearest hit of a ray with the axis-aligned cube [-half, half]^3 (slab method), or None.
    Used instead of a VTK picker, which cannot pick inside vtkAnnotatedCubeActor."""
    o, d = np.asarray(origin, dtype=float), np.asarray(direction, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        t1, t2 = (-half - o) / d, (half - o) / d
    t_near = np.nanmax(np.minimum(t1, t2))
    t_far = np.nanmin(np.maximum(t1, t2))
    if t_near > t_far or t_far < 0:
        return None
    return o + d * max(t_near, 0.0)


def view_for(piece) -> tuple[np.ndarray, np.ndarray]:
    """(unit direction from the focal point to the camera, view-up) for a cube piece."""
    d = np.asarray(piece, dtype=float)
    d /= np.linalg.norm(d)
    if tuple(piece) == (0, 0, 1):
        return d, np.array([-1.0, 0.0, 0.0])   # Top: Front at the bottom of the screen
    if tuple(piece) == (0, 0, -1):
        return d, np.array([1.0, 0.0, 0.0])    # Bottom: flipped over the front edge
    return d, np.array([0.0, 0.0, 1.0])


def slerp(a, b, t: float) -> np.ndarray:
    """Spherical interpolation of directions; antipodal inputs turn through a perpendicular."""
    a = np.asarray(a, dtype=float) / np.linalg.norm(a)
    b = np.asarray(b, dtype=float) / np.linalg.norm(b)
    dot = float(np.clip(a @ b, -1.0, 1.0))
    if dot > 0.9995:
        v = a + t * (b - a)
        return v / np.linalg.norm(v)
    if dot < -0.9995:
        perp = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(perp) < 1e-6:
            perp = np.cross(a, [0.0, 1.0, 0.0])
        perp /= np.linalg.norm(perp)
        return slerp(a, perp, 2 * t) if t < 0.5 else slerp(perp, b, 2 * t - 1)
    theta = np.arccos(dot)
    return (np.sin((1 - t) * theta) * a + np.sin(t * theta) * b) / np.sin(theta)


def _up_for(d, up) -> np.ndarray:
    """`up` made orthogonal to `d` (falls back to +Z / +X when parallel)."""
    for cand in (np.asarray(up, dtype=float), np.array([0.0, 0, 1]), np.array([1.0, 0, 0])):
        u = cand - (cand @ d) * d
        if np.linalg.norm(u) > 1e-6:
            return u / np.linalg.norm(u)
    return np.array([0.0, 0.0, 1.0])


class ViewCube:
    """Overlay renderer (layer 1) in the top-right corner, following the main camera's orientation."""

    def __init__(self, main_renderer, render_window, request_render, dpr: float = 1.0):
        self.main, self.window, self.request_render, self.dpr = main_renderer, render_window, request_render, dpr
        self.ren = vtkRenderer()
        self.ren.SetLayer(1)
        self.ren.InteractiveOff()
        render_window.SetNumberOfLayers(max(2, render_window.GetNumberOfLayers()))
        render_window.AddRenderer(self.ren)

        self.cube = vtkAnnotatedCubeActor()
        self.cube.SetXPlusFaceText("Front")
        self.cube.SetXMinusFaceText("Back")
        self.cube.SetYPlusFaceText("Right")
        self.cube.SetYMinusFaceText("Left")
        self.cube.SetZPlusFaceText("Top")
        self.cube.SetZMinusFaceText("Bottom")
        self.cube.SetFaceTextScale(0.16)
        self.cube.SetZFaceTextRotation(-90)  # read "Top" upright when Front (+X) faces the viewer
        self.cube.SetTextEdgesVisibility(False)
        self.ren.AddActor(self.cube)

        self._box = vtkCubeSource()
        mapper = vtkPolyDataMapper()
        mapper.SetInputConnection(self._box.GetOutputPort())
        self.highlight = vtkActor()
        self.highlight.SetMapper(mapper)
        self.highlight.PickableOff()
        self.highlight.VisibilityOff()
        self.highlight.GetProperty().SetOpacity(0.45)
        self.highlight.GetProperty().LightingOff()
        self.ren.AddActor(self.highlight)

        self._hover = None
        self._timer = None
        self.set_theme(th.current())
        main_renderer.AddObserver("StartEvent", self.sync)

    def set_theme(self, t) -> None:
        cube = self.cube.GetCubeProperty()
        cube.SetColor(*th.rgb(t.cube))
        cube.SetAmbient(0.55)   # flatter shading keeps the face labels readable from every side
        cube.SetDiffuse(0.5)
        for prop in (self.cube.GetXPlusFaceProperty(), self.cube.GetXMinusFaceProperty(),
                     self.cube.GetYPlusFaceProperty(), self.cube.GetYMinusFaceProperty(),
                     self.cube.GetZPlusFaceProperty(), self.cube.GetZMinusFaceProperty()):
            prop.SetColor(*th.rgb(t.text))
            prop.LightingOff()
        self.highlight.GetProperty().SetColor(*th.rgb(t.accent))

    def sync(self, *_) -> None:
        """Keep the corner viewport square and copy the main camera's direction."""
        w, h = self.window.GetSize()
        if w and h:
            s = SIZE_PX * self.dpr
            self.ren.SetViewport(max(0.0, 1 - s / w), max(0.0, 1 - s / h), 1.0, 1.0)
        cam, c = self.main.GetActiveCamera(), self.ren.GetActiveCamera()
        dop = np.array(cam.GetDirectionOfProjection())
        c.SetFocalPoint(0.0, 0.0, 0.0)
        c.SetPosition(*(-dop * 3.2))
        c.SetViewUp(*cam.GetViewUp())
        c.SetViewAngle(30.0)
        self.ren.ResetCameraClippingRange()

    def contains(self, x, y) -> bool:
        return bool(self.ren.IsInViewport(int(x), int(y)))

    def _world(self, x, y, z) -> np.ndarray:
        self.ren.SetDisplayPoint(float(x), float(y), z)
        self.ren.DisplayToWorld()
        p = np.array(self.ren.GetWorldPoint())
        return p[:3] / p[3]

    def _pick(self, x, y):
        if not self.contains(x, y):
            return None
        near, far = self._world(x, y, 0.0), self._world(x, y, 1.0)
        hit = ray_box(near, far - near)
        return None if hit is None else piece_at(hit)

    def _show_highlight(self, piece) -> None:
        if piece is None:
            self.highlight.VisibilityOff()
            return
        center, size = [], []
        for p in piece:
            if p:
                center.append(p * 0.5 * (1 + BAND) / 2)
                size.append(0.5 * (1 - BAND) + 0.02)
            else:
                center.append(0.0)
                size.append(BAND)
        self._box.SetCenter(*center)
        self._box.SetXLength(size[0])
        self._box.SetYLength(size[1])
        self._box.SetZLength(size[2])
        self.highlight.VisibilityOn()

    def on_move(self, x, y) -> bool:
        piece = self._pick(x, y)
        if piece != self._hover:
            self._hover = piece
            self._show_highlight(piece)
            self.request_render()
        return self.contains(x, y)

    def on_press(self, x, y) -> bool:
        """Snap on a piece; swallow every click inside the cube corner."""
        if not self.contains(x, y):
            return False
        piece = self._pick(x, y)
        if piece:
            self.snap(piece)
        return True

    def set_view(self, piece) -> None:
        """Jump to a piece's view immediately (keeps focal point and distance)."""
        cam = self.main.GetActiveCamera()
        d, up = view_for(piece)
        f = np.array(cam.GetFocalPoint())
        cam.SetPosition(*(f + d * cam.GetDistance()))
        cam.SetViewUp(*_up_for(d, up))
        self.main.ResetCameraClippingRange()

    def snap(self, piece, duration_ms: int = 200) -> None:
        cam = self.main.GetActiveCamera()
        f = np.array(cam.GetFocalPoint())
        dist = cam.GetDistance()
        d0 = (np.array(cam.GetPosition()) - f) / dist
        u0 = np.array(cam.GetViewUp())
        d1, u1 = view_for(piece)
        steps, state = 12, {"i": 0}
        if self._timer is not None:
            self._timer.stop()

        def tick():
            state["i"] += 1
            t = state["i"] / steps
            d = slerp(d0, d1, t)
            cam.SetPosition(*(f + d * dist))
            cam.SetViewUp(*_up_for(d, u0 + (u1 - u0) * t))
            self.main.ResetCameraClippingRange()
            self.request_render()
            if state["i"] >= steps:
                self._timer.stop()

        self._timer = QTimer()
        self._timer.setInterval(max(1, duration_ms // steps))
        self._timer.timeout.connect(tick)
        self._timer.start()
