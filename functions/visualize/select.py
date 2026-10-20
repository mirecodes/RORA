"""Interactive vedo UIs: part selection and joint-vector selection."""
from collections import defaultdict

import numpy as np
import vedo

from functions.math.geometry import normalize, rotmat
from functions.visualize.style import PASTEL_HEX, arrow_params, label_colors, pastel_hex, state_arrow, timed_show

QUIT_KEYS = ("q", "esc", "escape", "\x1b")
NEXT_STATE = {"None": "Revolute", "Revolute": "Prismatic"}  # anything else -> "None"


# =============================================================================
# Part selection
# =============================================================================
def select_parts(fragments, verts, faces, parts_num: int) -> list[list]:
    """Group convex fragments into parts 1..parts_num.
    Tab: next part (0 = view only), left click: assign, right click: undo, q/Esc: done.
    Returns parts[0..parts_num] (lists of fragments); unassigned fragments stay in part 1."""
    actors = [vedo.Mesh([verts, faces])]
    colors = [PASTEL_HEX[-1]]
    for i, fragment in enumerate(fragments, start=1):
        actor = vedo.Mesh([fragment.vertices, fragment.faces])
        actor.idx_fragment = i
        actors.append(actor)
        colors.append(pastel_hex(i))
    owner = [0] + [1] * len(fragments)
    prev = list(owner)
    mode = 0
    plt = vedo.Plotter(title="Part selection", size=(1800, 1800))

    def recolor():
        for i, actor in enumerate(actors):
            if mode == 0:
                actor.c(colors[i]).alpha(0.5)
            elif owner[i] == mode:
                actor.c("red").alpha(0.8)
            else:
                actor.c("lightblue").alpha(0.4)

    def on_click(event, undo: bool):
        if event.actor is None or mode == 0 or event.actor not in actors[1:]:
            return
        i = event.actor.idx_fragment
        if undo:
            owner[i] = prev[i]
        else:
            prev[i], owner[i] = owner[i], mode
        recolor()
        plt.render()

    def on_key(event):
        nonlocal mode
        k = getattr(event, "keypress", None)
        if str(k).lower() in QUIT_KEYS:
            plt.close()
            vedo.close()
        elif k in ("\t", "Tab"):
            mode = (mode + 1) % (parts_num + 1)
            recolor()
            plt.render()
            print(f"[info]: {'default mode' if mode == 0 else f'selection mode: part #{mode}'}")

    plt.add_callback("LeftButtonPress", lambda e: on_click(e, undo=False))
    plt.add_callback("RightButtonPress", lambda e: on_click(e, undo=True))
    plt.add_callback("KeyPress", on_key)
    recolor()
    timed_show(plt, actors, interactive=True)

    parts = [[] for _ in range(parts_num + 1)]
    for i, fragment in enumerate(fragments, start=1):
        parts[owner[i]].append(fragment)
    return parts


# =============================================================================
# Joint-vector selection (per part pair)
# =============================================================================
def _vector_of(actor) -> dict:
    return actor.bicon_dict["vectors"][actor.v_idx_in_bicon]


def _replace_arrow(plt, old, center, n, state, size, actors, idx2actor):
    new = state_arrow(center, n, state, size)
    new.vec_idx, new.bicon_dict, new.v_idx_in_bicon = old.vec_idx, old.bicon_dict, old.v_idx_in_bicon
    plt.add(new)
    plt.remove(old)
    actors[actors.index(old)] = new
    idx2actor[new.vec_idx] = new


def select_joint_vectors(bicons: list[dict], verts, faces, vert_label) -> None:
    """One window per part pair (i, j) showing all its candidate vectors; sets vector['state'] in place.
    Click: None -> Revolute (yellow) -> Prismatic (blue) -> None (gray).
    Keys move/rotate all vectors: W/S X, D/A Y, Space/Z Z; N/B X, J/H Y, I/U Z; q/Esc: next pair."""
    if not bicons:
        return
    size = arrow_params(verts, scale=0.8)  # slightly smaller than the debug views
    diag = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
    trans_step = diag * 0.02 if np.isfinite(diag) and diag > 0 else 1.0
    th = np.deg2rad(1.5)
    moves = {"w": (1, 0, 0), "s": (-1, 0, 0), "d": (0, 1, 0), "a": (0, -1, 0), " ": (0, 0, 1), "space": (0, 0, 1),
             "z": (0, 0, -1)}
    turns = {"i": ([0, 0, 1], th), "u": ([0, 0, 1], -th), "j": ([0, 1, 0], th), "h": ([0, 1, 0], -th),
             "n": ([1, 0, 0], th), "b": ([1, 0, 0], -th)}

    pair_map = defaultdict(list)
    for bicon in bicons:
        p, q = int(bicon["a"]["src"]), int(bicon["a"]["dst"])
        pair_map[(min(p, q), max(p, q))].append(bicon)

    for (p, q), group in pair_map.items():
        if p == 0 and q == 0:
            continue
        mesh = vedo.Mesh([verts, faces])
        mesh.pointcolors = label_colors(vert_label, keep=(p, q))
        mesh.alpha(0.4).pickable(False)

        actors, idx2actor = [], {}
        for bicon in group:
            for vi, v in enumerate(bicon.get("vectors") or []):
                n = normalize(v.get("n"))
                if not np.isfinite(n).all() or np.linalg.norm(n) < 1e-12:
                    continue
                c = np.asarray(v.get("center", bicon.get("center", [0, 0, 0])), dtype=float)
                arrow = state_arrow(c, n, v.get("state", "None"), size)
                arrow.vec_idx, arrow.bicon_dict, arrow.v_idx_in_bicon = len(actors), bicon, vi
                actors.append(arrow)
                idx2actor[arrow.vec_idx] = arrow

        plt = vedo.Plotter(title=f"Joint Selection: Parts {p} ↔ {q}", axes=0, size=(1800, 1800))
        for ev in ("KeyPressEvent", "KeyReleaseEvent", "CharEvent"):  # drop default VTK keybindings
            plt.interactor.RemoveObservers(ev)
        counter = [0]

        def on_click(event, plt=plt, actors=actors, idx2actor=idx2actor, counter=counter):
            act = getattr(event, "actor", None)
            if act is None or act not in actors:
                return
            v = _vector_of(act)
            state = NEXT_STATE.get(act.vec_state, "None")
            v["state"] = state
            if state == "Revolute":
                counter[0] += 1
                v["order"] = counter[0]
            elif state == "None":
                v["order"] = None
            c = np.asarray(v.get("center", act.bicon_dict.get("center", [0, 0, 0])), dtype=float)
            target = getattr(event, "plotter", None) or plt
            _replace_arrow(target, act, c, normalize(v.get("n", [0, 0, 1])), state, size, actors, idx2actor)
            target.render()

        def on_key(event, plt=plt, actors=actors, idx2actor=idx2actor):
            k = str(getattr(event, "keyPressed", None) or getattr(event, "key", None)
                    or getattr(event, "symbol", None) or getattr(event, "keypress", "") or "").lower()
            if k in QUIT_KEYS:
                plt.close()
                vedo.close()
                return
            d = np.asarray(moves.get(k, (0, 0, 0)), dtype=float) * trans_step
            R = rotmat(*turns[k]) if k in turns else None
            if not d.any() and R is None:
                return
            for act in list(actors):
                v = _vector_of(act)
                c = np.asarray(v.get("center", act.bicon_dict.get("center", [0, 0, 0])), dtype=float) + d
                v["center"] = c.tolist()
                if R is not None and v.get("n") is not None:
                    v["n"] = normalize(R @ normalize(v["n"])).tolist()
                n = normalize(v["n"])
                if np.isfinite(n).all() and np.linalg.norm(n) > 1e-12:
                    _replace_arrow(plt, act, c, n, act.vec_state, size, actors, idx2actor)
            plt.render()

        plt.add_callback("LeftButtonPress", on_click)
        plt.add_callback("KeyPress", on_key)
        plt.add_callback("CharEvent", on_key)

        print(f"[info] Joint Selection for Pair Parts {p} ↔ {q} ({len(actors)} vector candidates total):")
        print("  \033[37m[Gray Arrow]\033[0m Default Candidate (None)")
        print("  \033[38;2;255;255;0m[Yellow Arrow]\033[0m Click 1: Revolute Joint")
        print("  \033[38;2;0;0;255m[Blue Arrow]\033[0m Click 2: Prismatic Joint")
        timed_show(plt, [mesh, *actors], interactive=True).close()
