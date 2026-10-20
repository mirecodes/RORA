import time

import numpy as np
import vedo

from functions.utils.config import load_params

# Part colors: label k -> PASTEL[(k - 1) % len]
PASTEL_HEX = ["#66C5CC", "#F6CF71", "#F89C74", "#DCB0F2", "#87C55F", "#9EB9F3",
              "#FE88B1", "#C9DB74", "#8BE0A4", "#B497E7", "#B3B3B3"]
PASTEL = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in PASTEL_HEX], dtype=np.uint8)
BG_RGB = np.array([220, 220, 220], dtype=np.uint8)

# Joint vector states: color, radius scale, head length scale, alpha
STATE_STYLE = {
    "Revolute": ((255, 255, 0), 1.3, 1.15, 1.0),
    "Prismatic": ((0, 0, 255), 1.3, 1.15, 1.0),
    "None": ("gray", 0.7, 0.7, 0.45),
}


def pastel(label: int) -> np.ndarray:
    return PASTEL[(int(label) - 1) % len(PASTEL)]


def pastel_hex(label: int) -> str:
    return "#%02x%02x%02x" % tuple(pastel(label))


def label_colors(vert_label, keep=None) -> np.ndarray:
    """Per-vertex RGB: pastel for labels > 0 (or only those in `keep`), light gray otherwise."""
    lab = np.asarray(vert_label, dtype=int)
    rgb = PASTEL[(lab - 1) % len(PASTEL)]
    rgb[~(lab > 0 if keep is None else np.isin(lab, keep))] = BG_RGB
    return rgb


def arrow_params(verts: np.ndarray, scale: float = 1.0):
    """(arrow_len, shaft_rad, head_rad, head_len, sphere_rad) from the scene size,
    scaled by visualization.vector_scale in cfgs/parameters_cfg.yml."""
    try:
        vscale = load_params()["visualization"]["vector_scale"]
        lf, tf = float(vscale["length_factor"]), float(vscale["thickness_factor"])
    except Exception:
        lf, tf = 1.0, 1.0
    lf, tf = lf * scale, tf * scale
    diag = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
    arrow_len = (diag * 0.25 if np.isfinite(diag) and diag > 0 else 1.5) * lf
    r = arrow_len * 0.035 * tf
    return arrow_len, r * 3.5, r * 7.5, arrow_len * 0.30, arrow_len * 0.06 * tf


def state_arrow(center, n, state: str, size) -> vedo.Arrow:
    """Pickable joint-vector arrow styled by state ('None' | 'Revolute' | 'Prismatic')."""
    arrow_len, shaft_rad, head_rad, head_len = size[:4]
    color, s, hs, alpha = STATE_STYLE.get(state, STATE_STYLE["None"])
    arrow = vedo.Arrow(center, center + arrow_len * n, c=color, shaft_radius=shaft_rad * s,
                       head_radius=head_rad * s, head_length=head_len * hs).lighting("off")
    arrow.pickable(True)
    arrow.alpha(alpha)
    arrow.vec_state = state
    return arrow


def timed_show(plt, *args, **kwargs):
    """plt.show() that adds the blocking GUI time to functions.total_gui_time."""
    import functions
    t0 = time.time()
    out = plt.show(*args, **kwargs)
    functions.total_gui_time += time.time() - t0
    return out
