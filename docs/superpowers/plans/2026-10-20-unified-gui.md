# Unified Pipeline GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-stage vedo pop-up windows with one PySide6 window (3D viewport + side panel) that runs, re-runs, and times the pipeline, with editable parameters saved as object profiles.

**Architecture:** The pipeline runs on a worker thread. Stage code talks to the GUI only through `functions.gui.bridge.ui()`, which posts events to the GUI thread through a Qt signal and blocks on `threading.Event` for interactions and debug checkpoints. All vedo/VTK and Qt objects are created on the main thread inside `Scene.build()` / `Scene.widget()`. Pure logic (timing, run planning, transforms, interaction state, parameter files, view math) lives in Qt-free functions with plain-`assert` tests.

**Tech Stack:** Python 3.12 (`.venv`), PySide6, vedo 2025.5.4 / VTK 9.5 (`QVTKRenderWindowInteractor`), ruamel.yaml (round-trip yml), PyYAML (existing loader), numpy, scipy.

**Spec:** `docs/superpowers/specs/2026-10-20-unified-gui-design.md`

## Global Constraints

- All UI text, identifiers, comments, docstrings, log messages, and docs are in English (`CLAUDE.md`).
- Use the project venv: `.venv/bin/python`. Run tests from the repo root with `.venv/bin/python -m tests.<module>`.
- Tests are plain functions named `test_*` with a `__main__` runner (no pytest).
- `functions/gui/__init__.py` must not import Qt or VTK, so stage modules stay importable headless.
- Stage code imports GUI scenes lazily inside the function (`from functions.gui.scenes import ...`).
- Window: 16:9, default 1600×900; side panel 22% of width, clamped to 300–380 px; draggable splitter.
- The GUI never writes `cfgs/parameters_cfg.yml` or `cfgs/profiles/<profile>_params_cfg.yml`.
- Object profiles are full snapshots at `cfgs/profiles/objects/<object_name>_<YYYYMMDD>_<HHMMSS>.yml` with an `object` block and every stage section; `pipeline` is excluded.
- Align rotations pivot on the world origin. Articulate rotations turn each arrow about its own center.
- Key bindings (Align + Articulate): `W/S` ±X, `D/A` ±Y, `Space/Z` ±Z move; `N/B` ±X, `J/H` ±Y, `I/U` ±Z rotate; `Tab` next part; `R` reset view; `G` gizmo; `Enter` done.
- Default theme: dark. Joint colors: Revolute amber, Prismatic blue, None gray (from theme tokens).
- Commit after each task on branch `feat/unified-gui`, ending messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A string parameter that PyYAML would retype (`on`, `off`, `yes`, `""`) must still be the same string after Save and reload. Test in Task 2.
2. Two saves within the same second must create two files, newest listed first. Test in Task 2.
3. Running or re-running a stage whose upstream results are missing from `states.json` (fresh object) must refuse to start and name the missing stage. Test in Task 5.
4. Stop pressed while a stage waits for input, or while it is inside a long call, must end the stage as `stopped` at the next boundary without hanging the worker. Test in Task 5.
5. Articulate data with NaN or zero normals, vectors without `center`, or only the `(0, 0)` pair must not crash the scene; invalid vectors are skipped. Test in Task 6.

Also required by code (not unit-testable): if a scene's `build()` raises on the GUI thread, the window must resolve the bridge so the worker fails the stage instead of waiting forever (Task 13, `MainWindow._mount`).

## File Map

| File | Responsibility |
|---|---|
| `functions/utils/config.py` | Layered loading: base → shared profile → object profile (`load_object`, `load_params`). |
| `functions/gui/__init__.py` | Package marker (no imports). |
| `functions/gui/params_io.py` | Inline comments, widget-kind inference, snapshot save, `object_cfg.yml` update, profile listing. |
| `functions/gui/theme.py` | Light/dark tokens, Qt stylesheet. |
| `functions/gui/bridge.py` | `ui()`, `UiBridge`, `NullBridge`, `StageTimer`, `PipelineStopped`. |
| `functions/gui/runner.py` | Stage order, prerequisites, statuses, `PipelineRunner` worker, `timing.json`. |
| `functions/gui/manip.py` | 4×4 deltas, key bindings, `AssemblyTarget`, `VectorGroupTarget`. |
| `functions/gui/models.py` | `PartAssignment`, pair grouping, joint state cycling. |
| `functions/gui/viewcube.py` | View-cube math + overlay renderer. |
| `functions/gui/gizmo.py` | Gizmo drag math + overlay gizmo. |
| `functions/gui/viewport.py` | Qt-embedded vedo plotter, event router, overlays, scene mounting. |
| `functions/gui/scenes.py` | `Scene`, `CheckpointScene`, `AlignScene`, `PartSelectScene`, `JointSelectScene`. |
| `functions/gui/panel.py` | `Timeline`, `InteractionHost`, `ParamEditor`, `LogView`. |
| `functions/gui/window.py` | `MainWindow`: wiring, run control, events, theme, minimal mode, save. |
| `functions/gui/app.py` | `main(argv)` entry point. |
| `functions/pipeline/*.py`, `functions/visualize/plots.py`, `style.py` | Stage integration (`plan`/`step`/`checkpoint`/`interact`). |
| `functions/visualize/select.py` | Deleted. |
| `tests/test_*.py` | Logic tests per module. |

---

### Task 1: Branch, dependencies, and object-profile config layering

**Files:**
- Modify: `functions/utils/config.py`, `cfgs/object_cfg.yml`, `requirements.txt`, `.gitignore`
- Create: `tests/__init__.py`, `tests/test_config.py`, `cfgs/profiles/objects/.gitkeep`

**Interfaces:**
- Produces: `config.load_object_profile(stem) -> dict`, `config.load_object(object_profile=None) -> dict` (always sets `obj["object_profile"]` to the stem or `None`), `config.load_params(profile=None, object_profile=None) -> dict`. `object_profile=None` means "use `object_cfg.yml`"; `""` means "no object profile". Tests use `tests.test_config.temp_cfgs()`.

- [ ] **Step 1: Create the branch and install dependencies**

```bash
git checkout -b feat/unified-gui
uv pip install --python .venv/bin/python PySide6 "ruamel.yaml<0.19"
.venv/bin/python -c "import PySide6, ruamel.yaml; print(PySide6.__version__, ruamel.yaml.__version__)"
```

Append the two printed versions to `requirements.txt` in its existing `name==version` style, keeping alphabetical order (`PySide6==<printed>` after `pymeshlab`, `ruamel.yaml==<printed>` after `rpds-py`). `.gitignore` already has a `.superpowers` entry (added by the mockup server); keep it.

- [ ] **Step 2: Write the failing tests**

Create `tests/__init__.py` (empty) and `tests/test_config.py`:

```python
import os
import shutil
import tempfile
from contextlib import contextmanager

from functions.utils import config

ROOT_CFG = config.CFG_DIR


@contextmanager
def temp_cfgs():
    """Copy cfgs/ to a temp dir and point config.CFG_DIR at it."""
    old = config.CFG_DIR
    with tempfile.TemporaryDirectory() as tmp:
        dst = os.path.join(tmp, "cfgs")
        shutil.copytree(ROOT_CFG, dst)
        config.CFG_DIR = dst
        try:
            yield dst
        finally:
            config.CFG_DIR = old


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def test_no_object_profile_is_base_plus_shared_profile():
    with temp_cfgs():
        obj = config.load_object("")
        assert obj["object_profile"] is None
        base = config.load_cfg("parameters_cfg")
        shared = config.load_cfg(f"profiles/{obj['profile']}_params_cfg")
        assert config.load_params(object_profile="") == config._merge(base, shared)


def test_object_profile_overrides_params_and_object_block():
    with temp_cfgs() as d:
        write(os.path.join(d, "profiles", "objects", "toy_20260101_000000.yml"),
              "object:\n  object_name: toy\n  parts:\n    num: 7\n"
              "decompose:\n  coacd:\n    threshold: 0.33\n")
        obj = config.load_object("toy_20260101_000000")
        assert obj["object_name"] == "toy" and obj["parts"]["num"] == 7
        assert obj["object_profile"] == "toy_20260101_000000"
        params = config.load_params(object_profile="toy_20260101_000000")
        assert params["decompose"]["coacd"]["threshold"] == 0.33
        assert "object" not in params
        assert "stages" in params["pipeline"]  # pipeline still comes from the base file


def test_default_reads_object_cfg_and_missing_file_only_warns():
    with temp_cfgs() as d:
        path = os.path.join(d, "object_cfg.yml")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        write(path, text.replace("object_profile: null", "object_profile: missing_stem"))
        assert config.load_object()["object_profile"] == "missing_stem"
        assert config.load_params()["decompose"]["coacd"]  # loads without raising


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m tests.test_config`
Expected: FAIL with `AttributeError: module 'functions.utils.config' has no attribute 'load_object'`.

- [ ] **Step 4: Implement the layering**

In `cfgs/object_cfg.yml`, add after the `profile:` line:

```yaml

# GUI-saved snapshot cfgs/profiles/objects/<stem>.yml, applied after the shared profile (null = none)
object_profile: null
```

Create `cfgs/profiles/objects/.gitkeep` (empty). In `functions/utils/config.py`, replace `load_params` with:

```python
def load_object_profile(stem: str) -> dict:
    """cfgs/profiles/objects/<stem>.yml (a GUI-saved object snapshot); {} with a warning if missing."""
    path = os.path.join(CFG_DIR, "profiles", "objects", f"{stem}.yml")
    if not os.path.isfile(path):
        print(f"[warn]: object profile not found, skipped: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_object(object_profile: str | None = None) -> dict:
    """object_cfg.yml overlaid with the object profile's `object` block.
    `object_profile`: None = use object_cfg.yml's `object_profile`, "" = none."""
    obj = load_cfg("object_cfg")
    stem = (obj.get("object_profile") if object_profile is None else object_profile) or None
    if stem:
        obj = _merge(obj, load_object_profile(stem).get("object") or {})
    obj["object_profile"] = stem
    return obj


def load_params(profile: str | None = None, object_profile: str | None = None) -> dict:
    """parameters_cfg.yml, then cfgs/profiles/<profile>_params_cfg.yml, then the object profile without
    its `object` block. `profile` defaults to the object's `profile`; `object_profile` as in load_object."""
    obj = load_object(object_profile)
    profile = profile or obj.get("profile")
    params = load_cfg("parameters_cfg")
    if profile:
        params = _merge(params, load_cfg(f"profiles/{profile}_params_cfg"))
    if obj["object_profile"]:
        snapshot = load_object_profile(obj["object_profile"])
        snapshot.pop("object", None)
        params = _merge(params, snapshot)
    return params
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m tests.test_config && .venv/bin/python functions/utils/config.py`
Expected: `ok` twice.

- [ ] **Step 6: Commit**

```bash
git add .gitignore requirements.txt cfgs/object_cfg.yml cfgs/profiles/objects/.gitkeep functions/utils/config.py tests/__init__.py tests/test_config.py CLAUDE.md docs/superpowers
git commit -m "feat(config): layer GUI object profiles over shared params

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Parameter files (`params_io`)

**Files:**
- Create: `functions/gui/__init__.py`, `functions/gui/params_io.py`, `tests/test_params_io.py`

**Interfaces:**
- Consumes: `config.CFG_DIR`, `config.load_params`, `config.load_object` (Task 1), `tests.test_config.temp_cfgs`.
- Produces:
  - `STAGE_SECTIONS: list[str]`, `OBJECT_KEYS: list[str]`, `objects_dir() -> str`
  - `inline_comments(node, prefix=()) -> dict[tuple, str]`, `load_comments() -> dict[tuple, str]` (object keys under `("object", key)`)
  - `field_kind(value, comment="") -> tuple[str, list[str]]` with kinds `bool | int | float | percent | null | choice | str`
  - `build_snapshot(params, obj) -> CommentedMap`, `save_object_profile(params, obj, now=None) -> str` (stem)
  - `update_object_cfg(**values) -> None`, `list_object_profiles(object_name) -> list[str]` (newest first)

- [ ] **Step 1: Write the failing tests**

Create `functions/gui/__init__.py`:

```python
"""Unified pipeline GUI (PySide6 + vedo). Keep this file free of Qt/VTK imports."""
```

Create `tests/test_params_io.py`:

```python
import hashlib
import os
from datetime import datetime

from functions.gui import params_io
from functions.utils import config
from tests.test_config import temp_cfgs, write

NOW = datetime(2026, 10, 20, 14, 30, 12)


def _digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _shared_files(d):
    profiles = os.path.join(d, "profiles")
    return [os.path.join(d, "parameters_cfg.yml")] + [
        os.path.join(profiles, n) for n in os.listdir(profiles) if n.endswith("_params_cfg.yml")]


def test_field_kind():
    assert params_io.field_kind(True) == ("bool", [])
    assert params_io.field_kind(3) == ("int", [])
    assert params_io.field_kind(0.5) == ("float", [])
    assert params_io.field_kind(None) == ("null", [])
    assert params_io.field_kind("20%") == ("percent", [])
    assert params_io.field_kind("all", "# single_plane | rbf | multi_plane | all") == \
        ("choice", ["single_plane", "rbf", "multi_plane", "all"])
    assert params_io.field_kind("scale", "") == ("str", [])
    assert params_io.field_kind("x", "# a | b") == ("str", [])  # value not among the choices


def test_load_comments_finds_choices():
    comments = params_io.load_comments()
    kind, choices = params_io.field_kind("pymeshlab", comments[("refine", "method")])
    assert kind == "choice" and "point2mesh" in choices
    kind, choices = params_io.field_kind("real_object", comments[("object", "profile")])
    assert kind == "choice" and "partnet_object" in choices


def test_snapshot_save_and_reload():
    with temp_cfgs() as d:
        obj = config.load_object("")
        params = config.load_params(object_profile="")
        params["decompose"]["coacd"]["threshold"] = 0.2
        params["decompose"]["coacd"]["preprocess_mode"] = "on"  # PyYAML would read bare `on` as True
        params["articulate"]["urdf"]["urdf_name"] = ""
        obj["parts"]["num"] = 5
        before = {p: _digest(p) for p in _shared_files(d)}

        stem = params_io.save_object_profile(params, obj, now=NOW)

        assert stem == f"{obj['object_name']}_20261020_143012"
        assert {p: _digest(p) for p in _shared_files(d)} == before  # shared files untouched
        with open(os.path.join(d, "profiles", "objects", f"{stem}.yml"), encoding="utf-8") as f:
            text = f.read()
        assert text.startswith("# Object profile for")
        assert "\npipeline:" not in text and not text.startswith("pipeline:")
        assert "# concavity" in text  # base comments carried over
        with open(os.path.join(d, "object_cfg.yml"), encoding="utf-8") as f:
            obj_text = f.read()
        assert f"object_profile: {stem}" in obj_text and obj_text.startswith("# Target object")

        reloaded = config.load_params()  # default: object_cfg.yml now points at the snapshot
        for section in params_io.STAGE_SECTIONS:
            assert reloaded[section] == params[section], section
        assert reloaded["decompose"]["coacd"]["preprocess_mode"] == "on"
        assert reloaded["articulate"]["urdf"]["urdf_name"] == ""
        assert config.load_object()["parts"]["num"] == 5


def test_same_second_saves_and_listing():
    with temp_cfgs() as d:
        obj = config.load_object("")
        params = config.load_params(object_profile="")
        first = params_io.save_object_profile(params, obj, now=NOW)
        second = params_io.save_object_profile(params, obj, now=NOW)
        assert second == first + "_2"
        write(os.path.join(d, "profiles", "objects", "other_20261020_143012.yml"), "object: {}\n")
        assert params_io.list_object_profiles(obj["object_name"]) == [second, first]


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m tests.test_params_io`
Expected: FAIL with `ImportError: cannot import name 'params_io'`.

- [ ] **Step 3: Implement `functions/gui/params_io.py`**

```python
"""Parameter files for the GUI: inline-comment lookup, widget-kind inference, and object profile
snapshots (cfgs/profiles/objects/<object>_<YYYYMMDD>_<HHMMSS>.yml). Shared files are never written."""
import copy
import glob
import io
import os
import re
from datetime import datetime

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from functions.utils import config

# Snapshot content: everything that defines an object's run except `pipeline` (run settings).
STAGE_SECTIONS = ["transform", "refine", "decompose", "segment", "articulate", "bind", "visualization"]
OBJECT_KEYS = ["object_name", "extension", "profile", "parts"]

_PERCENT = re.compile(r"^-?\d+(\.\d+)?%$")
_CHOICES = re.compile(r"#\s*([\w.-]+(?:\s*\|\s*[\w.-]+)+)")


def objects_dir() -> str:
    return os.path.join(config.CFG_DIR, "profiles", "objects")


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096
    y.representer.add_representer(type(None), lambda r, _: r.represent_scalar("tag:yaml.org,2002:null", "null"))
    return y


def _load_rt(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return _yaml().load(f)


def _dump_atomic(doc, path: str) -> None:
    """Serialize first, then write a temp file and os.replace, so a failure never leaves a partial yml."""
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    os.replace(tmp, path)


def inline_comments(node, prefix: tuple = ()) -> dict:
    """{key path: first line of the inline comment} for a ruamel CommentedMap."""
    out = {}
    if not isinstance(node, CommentedMap):
        return out
    for key, value in node.items():
        path = prefix + (key,)
        tokens = node.ca.items.get(key)
        if tokens and len(tokens) > 2 and tokens[2] is not None:
            lines = tokens[2].value.strip().splitlines()
            if lines:
                out[path] = lines[0].strip()
        out.update(inline_comments(value, path))
    return out


def load_comments() -> dict:
    """Inline comments of parameters_cfg.yml and object_cfg.yml (object keys under ('object', key))."""
    params = inline_comments(_load_rt(os.path.join(config.CFG_DIR, "parameters_cfg.yml")))
    obj = inline_comments(_load_rt(os.path.join(config.CFG_DIR, "object_cfg.yml")), ("object",))
    return {**params, **obj}


def field_kind(value, comment: str = "") -> tuple[str, list[str]]:
    """Widget kind for a yml value: bool | int | float | percent | null | choice | str (+ choices).
    A string becomes a choice when its inline comment lists `a | b | c` and includes the value."""
    if isinstance(value, bool):
        return "bool", []
    if isinstance(value, int):
        return "int", []
    if isinstance(value, float):
        return "float", []
    if value is None:
        return "null", []
    if isinstance(value, str) and _PERCENT.match(value):
        return "percent", []
    m = _CHOICES.search(comment or "")
    if m:
        choices = [c.strip() for c in m.group(1).split("|")]
        if str(value) in choices:
            return "choice", choices
    return "str", []


def _scalar(value):
    """Quote strings that PyYAML (YAML 1.1, used by the loader) would read back as another type."""
    if isinstance(value, str):
        try:
            same = yaml.safe_load(value) == value
        except yaml.YAMLError:
            same = False
        if not same:
            return DoubleQuotedScalarString(value)
    return value


def _assign(node: CommentedMap, values: dict) -> None:
    """Make `node` hold exactly `values`, keeping comments and key order of the keys that stay."""
    for key in [k for k in node if k not in values]:
        del node[key]
    for key, value in values.items():
        if isinstance(value, dict):
            if not isinstance(node.get(key), CommentedMap):
                node[key] = CommentedMap()
            _assign(node[key], value)
        elif key not in node or node[key] != value:
            node[key] = _scalar(value)


def build_snapshot(params: dict, obj: dict) -> CommentedMap:
    """`object` block + every stage section (no `pipeline`), carrying parameters_cfg.yml comments."""
    base = _load_rt(os.path.join(config.CFG_DIR, "parameters_cfg.yml"))
    doc = CommentedMap()
    doc["object"] = CommentedMap()
    _assign(doc["object"], {k: copy.deepcopy(obj[k]) for k in OBJECT_KEYS if k in obj})
    for section in STAGE_SECTIONS:
        if section not in params:
            continue
        node = base.get(section)
        if not isinstance(node, CommentedMap):
            node = CommentedMap()
        _assign(node, params[section])
        doc[section] = node
    return doc


def update_object_cfg(**values) -> None:
    """Set top-level keys of object_cfg.yml in place (comments and key order kept)."""
    path = os.path.join(config.CFG_DIR, "object_cfg.yml")
    doc = _load_rt(path)
    for key, value in values.items():
        doc[key] = _scalar(value)
    _dump_atomic(doc, path)


def save_object_profile(params: dict, obj: dict, now: datetime | None = None) -> str:
    """Write a full snapshot to cfgs/profiles/objects/, point object_cfg.yml at it, return its stem."""
    now = now or datetime.now()
    name = obj["object_name"]
    os.makedirs(objects_dir(), exist_ok=True)
    stem, n = f"{name}_{now:%Y%m%d_%H%M%S}", 2
    while os.path.exists(os.path.join(objects_dir(), f"{stem}.yml")):
        stem, n = f"{name}_{now:%Y%m%d_%H%M%S}_{n}", n + 1
    doc = build_snapshot(params, obj)
    doc.yaml_set_start_comment(
        f"Object profile for {name}, saved {now:%Y-%m-%d %H:%M:%S} by the RORA GUI.\n"
        f"Shared profile at save time: {obj.get('profile')}.\n"
        "Loaded after parameters_cfg.yml and the shared profile. `pipeline` (run settings) is not stored here.")
    _dump_atomic(doc, os.path.join(objects_dir(), f"{stem}.yml"))
    update_object_cfg(object_profile=stem, object_name=name)
    return stem


def list_object_profiles(object_name: str) -> list[str]:
    """Stems of saved profiles for `object_name`, newest first."""
    pattern = re.compile(rf"^{re.escape(object_name)}_\d{{8}}_\d{{6}}(_\d+)?$")
    stems = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(objects_dir(), "*.yml"))]
    return sorted((s for s in stems if pattern.match(s)), reverse=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m tests.test_params_io`
Expected: `ok`. If `"# concavity" in text` fails, print `text` and check that the `decompose.coacd.threshold` comment in `parameters_cfg.yml` still starts with `# concavity`; adjust the assertion to the actual comment, not the code.

- [ ] **Step 5: Commit**

```bash
git add functions/gui/__init__.py functions/gui/params_io.py tests/test_params_io.py
git commit -m "feat(gui): object profile snapshots and parameter field kinds

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Theme tokens and themed joint colors

**Files:**
- Create: `functions/gui/theme.py`
- Modify: `functions/visualize/style.py:14-19` (`STATE_STYLE`) and `state_arrow`

**Interfaces:**
- Produces: `Theme` (frozen dataclass of hex strings: `name, bg, panel, line, text, text2, text3, accent, ok, warn, err, button, vp_top, vp_bottom, mesh, revolute, prismatic, none, axis_x, axis_y, axis_z, hover`), `DARK`, `LIGHT`, `current() -> Theme`, `set_current(t)`, `rgb(hex) -> (r, g, b)` in 0..1, `stylesheet(t) -> str`. In `style.py`: `STATE_SHAPE`, `state_color(state) -> str`; `state_arrow` signature unchanged.

- [ ] **Step 1: Create `functions/gui/theme.py`**

```python
"""Light/dark design tokens shared by the Qt widgets and the VTK viewport. Qt-free."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str          # window background
    panel: str       # side panel and header
    line: str        # borders, timeline rail
    text: str        # primary text
    text2: str       # secondary text
    text3: str       # muted text, section headers
    accent: str      # current step, selection, primary button
    ok: str          # done
    warn: str        # stale
    err: str         # failed
    button: str      # secondary button and input background
    vp_top: str      # viewport gradient (top)
    vp_bottom: str   # viewport gradient (bottom)
    mesh: str        # neutral mesh color
    revolute: str
    prismatic: str
    none: str        # unselected joint candidate, muted geometry
    axis_x: str
    axis_y: str
    axis_z: str
    hover: str       # gizmo / view cube hover highlight


DARK = Theme("dark", bg="#1b1d22", panel="#1f2127", line="#2c2f36", text="#e8eaee", text2="#b5bac3",
             text3="#7d838e", accent="#6aa9ff", ok="#5fb37e", warn="#e0a43a", err="#e06c6c", button="#2a2d34",
             vp_top="#2a2e36", vp_bottom="#1e2026", mesh="#8fb4d8", revolute="#F2B33D", prismatic="#4F8DF5",
             none="#8a8f98", axis_x="#e06c6c", axis_y="#6cc58a", axis_z="#6aa9ff", hover="#ffffff")
LIGHT = Theme("light", bg="#f4f5f7", panel="#ffffff", line="#e2e4e8", text="#1d2027", text2="#4a505b",
              text3="#8a909a", accent="#2f6fdc", ok="#2f9e5d", warn="#c98a1b", err="#cc4b4b", button="#f0f1f4",
              vp_top="#fbfbfc", vp_bottom="#e2e5ea", mesh="#7a9cc0", revolute="#D99A1E", prismatic="#2F6FDC",
              none="#a3a8b1", axis_x="#d0503f", axis_y="#3f9e5a", axis_z="#2f6fdc", hover="#000000")

_current = DARK


def current() -> Theme:
    return _current


def set_current(theme: Theme) -> None:
    global _current
    _current = theme


def rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def stylesheet(t: Theme) -> str:
    """Qt stylesheet for the whole app. Widgets pick rules through objectName and dynamic properties."""
    return f"""
QWidget {{ background: {t.panel}; color: {t.text2}; font-size: 12px; }}
QMainWindow {{ background: {t.bg}; }}
QWidget#Header {{ border-bottom: 1px solid {t.line}; }}
QWidget#Panel {{ border-left: 1px solid {t.line}; }}
QFrame#Divider {{ background: {t.line}; min-height: 1px; max-height: 1px; }}
QLabel#Title {{ color: {t.text}; font-weight: 600; font-size: 13px; }}
QLabel#Section {{ color: {t.text3}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
QLabel#Muted {{ color: {t.text3}; }}
QLabel#Meta {{ color: {t.text3}; font-family: Menlo, monospace; font-size: 10px; }}
QLabel#Modified {{ color: {t.accent}; }}
QPushButton {{ background: {t.button}; color: {t.text}; border: 1px solid {t.line}; border-radius: 5px; padding: 4px 10px; }}
QPushButton:hover {{ border-color: {t.accent}; }}
QPushButton:disabled {{ color: {t.text3}; }}
QPushButton:checked {{ border-color: {t.accent}; background: {t.bg}; }}
QPushButton[primary="true"] {{ background: {t.accent}; border-color: {t.accent}; color: #ffffff; }}
QToolButton {{ background: transparent; border: none; color: {t.text2}; padding: 2px 4px; }}
QToolButton:hover {{ color: {t.text}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {t.button}; color: {t.text}; border: 1px solid {t.line}; border-radius: 4px; padding: 2px 6px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {t.accent}; }}
QPlainTextEdit {{ background: {t.bg}; color: {t.text2}; border: 1px solid {t.line}; font-family: Menlo, monospace; font-size: 11px; }}
QScrollArea {{ border: none; }}
QSplitter::handle {{ background: {t.line}; }}
QLabel#Dot {{ border: 2px solid {t.line}; border-radius: 6px; min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px; }}
QLabel#Dot[state="running"], QLabel#Dot[state="waiting"] {{ background: {t.accent}; border-color: {t.accent}; }}
QLabel#Dot[state="done"] {{ background: {t.ok}; border-color: {t.ok}; }}
QLabel#Dot[state="cached"] {{ background: {t.text3}; border-color: {t.text3}; }}
QLabel#Dot[state="stale"] {{ border-color: {t.warn}; }}
QLabel#Dot[state="failed"] {{ background: {t.err}; border-color: {t.err}; }}
QLabel#StageName {{ color: {t.text2}; }}
QLabel#StageName[state="pending"], QLabel#StageName[state="stopped"] {{ color: {t.text3}; }}
QLabel#StageName[state="running"], QLabel#StageName[state="waiting"] {{ color: {t.text}; font-weight: 600; }}
QWidget#SubSteps {{ border-left: 2px solid {t.line}; margin-left: 5px; }}
QLabel#SubDot {{ background: {t.line}; border-radius: 3px; min-width: 6px; max-width: 6px; min-height: 6px; max-height: 6px; }}
QLabel#SubDot[state="running"], QLabel#SubDot[state="waiting"] {{ background: {t.accent}; }}
QLabel#SubDot[state="done"] {{ background: {t.ok}; }}
QLabel#SubDot[state="failed"] {{ background: {t.err}; }}
QLabel#SubDot[state="skipped"] {{ background: transparent; border: 1px solid {t.line}; }}
QLabel#SubName {{ color: {t.text2}; font-size: 11px; }}
QLabel#SubName[state="pending"] {{ color: {t.text3}; }}
QLabel#SubName[state="skipped"] {{ color: {t.text3}; text-decoration: line-through; }}
QLabel#SubName[state="running"], QLabel#SubName[state="waiting"] {{ color: {t.text}; }}
"""
```

- [ ] **Step 2: Theme the joint colors in `functions/visualize/style.py`**

Add `from functions.gui import theme` to the imports. Replace the `STATE_STYLE` block and `state_arrow` with:

```python
# Joint vector states: radius scale, head length scale, alpha (colors come from the active theme)
STATE_SHAPE = {
    "Revolute": (1.3, 1.15, 1.0),
    "Prismatic": (1.3, 1.15, 1.0),
    "None": (0.7, 0.7, 0.45),
}


def state_color(state: str) -> str:
    t = theme.current()
    return {"Revolute": t.revolute, "Prismatic": t.prismatic}.get(state, t.none)


def state_arrow(center, n, state: str, size) -> vedo.Arrow:
    """Pickable joint-vector arrow styled by state ('None' | 'Revolute' | 'Prismatic')."""
    arrow_len, shaft_rad, head_rad, head_len = size[:4]
    s, hs, alpha = STATE_SHAPE.get(state, STATE_SHAPE["None"])
    arrow = vedo.Arrow(center, center + arrow_len * n, c=state_color(state), shaft_radius=shaft_rad * s,
                       head_radius=head_rad * s, head_length=head_len * hs).lighting("off")
    arrow.pickable(True)
    arrow.alpha(alpha)
    arrow.vec_state = state
    return arrow
```

- [ ] **Step 3: Verify**

Run: `grep -rn "STATE_STYLE" functions; .venv/bin/python -c "from functions.visualize.style import state_arrow, state_color; from functions.gui.theme import stylesheet, DARK, LIGHT; import numpy as np; a = state_arrow(np.zeros(3), np.array([0,0,1.]), 'Revolute', (1, .03, .07, .3)); print(state_color('Revolute'), len(stylesheet(DARK)) > 0, len(stylesheet(LIGHT)) > 0)"`
Expected: no `STATE_STYLE` matches; prints `#F2B33D True True`.

- [ ] **Step 4: Commit**

```bash
git add functions/gui/theme.py functions/visualize/style.py
git commit -m "feat(gui): light/dark theme tokens and themed joint colors

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Bridge and stage timer

**Files:**
- Create: `functions/gui/bridge.py`, `tests/test_bridge.py`

**Interfaces:**
- Produces:
  - `PipelineStopped(Exception)`
  - `StageTimer(clock=time.perf_counter)`: `begin_stage(name)`, `begin_step(key) -> (prev_key, compute) | None`, `add_wait(seconds)`, `end_stage() -> (key, compute) | None`, `reset()`, `report() -> {stage: {"compute", "wait", "wall", "steps": {key: {"compute", "wait"}}}}`, `summary() -> str`, attribute `stages`.
  - `NullBridge`: `debug=False`, `minimal=False`, no-op `plan/step/checkpoint/check_stop`; `interact` raises `RuntimeError`.
  - `UiBridge(post, *, minimal=False, clock=time.perf_counter)`: attributes `post`, `debug`, `minimal`, `timer`. Runner side: `begin_stage(name)`, `end_stage(name, status, error=None)`. Stage side: `plan(steps)`, `step(key)`, `checkpoint(title, build)`, `interact(scene)`, `check_stop()`. GUI side: `resolve(result=None)`, `request_stop()`, `reset_stop()`.
  - Events posted as `post(kind, payload)`: `("stage_begin", name)`, `("plan", [(key, label, enabled), ...])`, `("step", {"key": key, "closed": (prev_key, compute) | None})`, `("checkpoint", (title, build))`, `("scene", scene)`, `("stage_end", {"name", "status", "error", "report", "closed"})`. The runner posts `("run_end", None)`.
  - `ui()`, `set_ui(bridge)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bridge.py`:

```python
import threading

from functions.gui import bridge
from functions.gui.bridge import NullBridge, PipelineStopped, StageTimer, UiBridge


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_timer_compute_excludes_wait():
    clock = FakeClock()
    timer = StageTimer(clock)
    timer.begin_stage("refine")
    assert timer.begin_step("a") is None
    clock.t += 2.0
    assert timer.begin_step("b") == ("a", 2.0)
    clock.t += 6.0
    timer.add_wait(5.0)
    assert timer.end_stage() == ("b", 1.0)
    r = timer.report()["refine"]
    assert (r["wall"], r["wait"], r["compute"]) == (8.0, 5.0, 3.0)
    assert r["steps"] == {"a": {"compute": 2.0, "wait": 0.0}, "b": {"compute": 1.0, "wait": 5.0}}
    assert "refine" in timer.summary()


def test_repeated_step_accumulates_and_stage_rerun_replaces():
    clock = FakeClock()
    timer = StageTimer(clock)
    timer.begin_stage("refine")
    timer.begin_step("load"); clock.t += 1.0
    timer.begin_step("save"); clock.t += 1.0
    timer.begin_step("load"); clock.t += 2.0
    timer.end_stage()
    assert timer.report()["refine"]["steps"]["load"]["compute"] == 3.0
    timer.begin_stage("refine"); clock.t += 0.5; timer.end_stage()
    assert timer.report()["refine"]["wall"] == 0.5 and timer.report()["refine"]["steps"] == {}


def test_events_and_interact_result():
    events = []
    b = UiBridge(lambda kind, payload: events.append((kind, payload)))
    b.begin_stage("segment")
    b.plan([("load", "Load", True)])
    b.step("load")
    threading.Timer(0.05, lambda: b.resolve("owners")).start()
    assert b.interact("scene-object") == "owners"
    b.end_stage("segment", "done")
    kinds = [k for k, _ in events]
    assert kinds == ["stage_begin", "plan", "step", "scene", "stage_end"]
    end = events[-1][1]
    assert end["name"] == "segment" and end["status"] == "done" and end["closed"][0] == "load"
    assert end["report"]["wait"] > 0.0


def test_stop_unblocks_waiting_worker():
    b = UiBridge(lambda kind, payload: None)
    b.begin_stage("segment")
    threading.Timer(0.05, b.request_stop).start()
    try:
        b.interact("scene")
        raise AssertionError("expected PipelineStopped")
    except PipelineStopped:
        pass
    try:
        b.step("next")
        raise AssertionError("expected PipelineStopped")
    except PipelineStopped:
        pass
    b.reset_stop()
    b.step("next")  # no longer stopped


def test_checkpoint_is_noop_unless_debug():
    events = []
    b = UiBridge(lambda kind, payload: events.append(kind))
    b.begin_stage("refine")
    b.checkpoint("title", lambda: [])
    assert "checkpoint" not in events
    b.debug = True
    threading.Timer(0.05, b.resolve).start()
    b.checkpoint("title", lambda: [])
    assert "checkpoint" in events


def test_default_ui_is_null_bridge():
    assert isinstance(bridge.ui(), NullBridge)
    bridge.ui().step("x")
    try:
        bridge.ui().interact("scene")
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m tests.test_bridge`
Expected: FAIL with `ImportError: cannot import name 'bridge'`.

- [ ] **Step 3: Implement `functions/gui/bridge.py`**

```python
"""Thread-safe bridge between pipeline stage code (worker thread) and the GUI (main thread).

Stage code only calls ui(). The GUI installs a UiBridge with set_ui(); without a GUI, ui() returns a
NullBridge, so stage modules stay importable and the non-interactive parts can run headless.
A future ReplayBridge (answers interact() from states.json) can be installed the same way."""
import threading
import time
from typing import Any, Callable


class PipelineStopped(Exception):
    """Raised in the worker thread when the user presses Stop."""


class StageTimer:
    """Per-stage and per-step wall time and wait time (blocked on user input). compute = wall - wait."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter):
        self.clock = clock
        self.reset()

    def reset(self) -> None:
        self.stages: dict[str, dict] = {}
        self._stage = None
        self._step = None
        self._t_stage = self._t_step = 0.0

    def begin_stage(self, name: str) -> None:
        self.end_stage()
        self._stage = name
        self.stages[name] = {"wall": 0.0, "wait": 0.0, "steps": {}}
        self._t_stage = self.clock()

    def _close_step(self):
        if self._step is None:
            return None
        step = self.stages[self._stage]["steps"][self._step]
        step["wall"] += self.clock() - self._t_step
        closed = (self._step, step["wall"] - step["wait"])
        self._step = None
        return closed

    def begin_step(self, key: str):
        """Start `key`; return (previous key, its compute seconds) or None."""
        if self._stage is None:
            return None
        closed = self._close_step()
        self._step = key
        self._t_step = self.clock()
        self.stages[self._stage]["steps"].setdefault(key, {"wall": 0.0, "wait": 0.0})
        return closed

    def add_wait(self, seconds: float) -> None:
        if self._stage is None:
            return
        stage = self.stages[self._stage]
        stage["wait"] += seconds
        if self._step is not None:
            stage["steps"][self._step]["wait"] += seconds

    def end_stage(self):
        """Close the stage; return its last step as (key, compute seconds) or None."""
        if self._stage is None:
            return None
        closed = self._close_step()
        self.stages[self._stage]["wall"] = self.clock() - self._t_stage
        self._stage = None
        return closed

    def report(self) -> dict:
        return {name: {"compute": s["wall"] - s["wait"], "wait": s["wait"], "wall": s["wall"],
                       "steps": {k: {"compute": v["wall"] - v["wait"], "wait": v["wait"]}
                                 for k, v in s["steps"].items()}}
                for name, s in self.stages.items()}

    def summary(self) -> str:
        rows = self.report()
        lines = ["=" * 44, f"{'Pipeline timing (seconds)':^44}", "=" * 44,
                 f"{'stage':<14}{'compute':>10}{'wait':>10}{'wall':>10}"]
        for name, r in rows.items():
            lines.append(f"{name:<14}{r['compute']:>10.2f}{r['wait']:>10.2f}{r['wall']:>10.2f}")
        total = [sum(r[k] for r in rows.values()) for k in ("compute", "wait", "wall")]
        lines += ["-" * 44, f"{'total':<14}{total[0]:>10.2f}{total[1]:>10.2f}{total[2]:>10.2f}", "=" * 44]
        return "\n".join(lines)


class NullBridge:
    """Headless default: progress calls are no-ops; interaction needs the GUI."""
    debug = False
    minimal = False

    def plan(self, steps) -> None:
        pass

    def step(self, key: str) -> None:
        pass

    def checkpoint(self, title: str, build) -> None:
        pass

    def check_stop(self) -> None:
        pass

    def interact(self, scene):
        raise RuntimeError("This stage needs user input. Start the GUI with scripts/run_pipeline.sh.")


class UiBridge:
    """Called from the worker thread. `post(kind, payload)` must hand events to the GUI thread
    (a Qt signal emit); interact()/checkpoint() block until the GUI calls resolve() or request_stop()."""

    def __init__(self, post: Callable[[str, Any], None], *, minimal: bool = False,
                 clock: Callable[[], float] = time.perf_counter):
        self.post = post
        self.minimal = minimal
        self.debug = False  # set by the runner per stage: cfgs.debug_mode and not minimal
        self.timer = StageTimer(clock)
        self._stop = threading.Event()
        self._done = threading.Event()
        self._result = None

    # --- runner side ---
    def begin_stage(self, name: str) -> None:
        self.timer.begin_stage(name)
        self.post("stage_begin", name)

    def end_stage(self, name: str, status: str, error: str | None = None) -> None:
        closed = self.timer.end_stage()
        self.post("stage_end", {"name": name, "status": status, "error": error,
                                "report": self.timer.report().get(name), "closed": closed})

    # --- stage side ---
    def plan(self, steps) -> None:
        """Declare (key, label, enabled) sub-steps; repeated calls append keys not seen yet."""
        self.post("plan", [tuple(s) for s in steps])

    def step(self, key: str) -> None:
        self.check_stop()
        self.post("step", {"key": key, "closed": self.timer.begin_step(key)})

    def checkpoint(self, title: str, build) -> None:
        """Show `build()` (run on the GUI thread) until Continue. No-op unless debug is on."""
        if self.debug:
            self._block("checkpoint", (title, build))

    def interact(self, scene):
        return self._block("scene", scene)

    def check_stop(self) -> None:
        if self._stop.is_set():
            raise PipelineStopped()

    def _block(self, kind: str, payload):
        self.check_stop()
        self._done.clear()
        self._result = None
        t0 = self.timer.clock()
        self.post(kind, payload)
        self._done.wait()
        self.timer.add_wait(self.timer.clock() - t0)
        self.check_stop()
        return self._result

    # --- GUI side ---
    def resolve(self, result=None) -> None:
        self._result = result
        self._done.set()

    def request_stop(self) -> None:
        self._stop.set()
        self._done.set()

    def reset_stop(self) -> None:
        self._stop.clear()


_active = NullBridge()


def ui():
    """The bridge stage code reports to (NullBridge until the GUI installs one)."""
    return _active


def set_ui(bridge) -> None:
    global _active
    _active = bridge
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m tests.test_bridge`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add functions/gui/bridge.py tests/test_bridge.py
git commit -m "feat(gui): thread-safe UI bridge and stage timer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Pipeline runner and stage table

**Files:**
- Create: `functions/gui/runner.py`, `tests/test_runner.py`
- Modify: `functions/pipeline/interface.py` (stage table, `run_stage`, `SystemConfigs` default `obj`; delete `execute_pipeline`)

**Interfaces:**
- Consumes: `UiBridge`, `PipelineStopped`, `set_ui` (Task 4); `config.load_object` (Task 1).
- Produces in `runner.py`: `STAGE_ORDER`, `STAGE_LABELS`, `PREREQS`, `PRODUCES`, `read_states(path) -> dict`, `missing_prereqs(stage, available, restore_align=False) -> list[str]`, `first_blocked(stages, states, restore_align=False) -> (stage, missing) | None`, `initial_statuses(states) -> dict`, `stale_after(statuses, rerun) -> dict`, `stages_from(stage, enabled) -> list[str]`, `write_timing(attr_dir, report, started, minimal) -> str`, `PipelineRunner(bridge, make_cfgs, run_stage)` with `start(stages)`, `busy`, `join(timeout=None)`.
- Produces in `interface.py`: `STAGE_FUNCS`, `run_stage(cfgs, name)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_runner.py`:

```python
import json
import os
import tempfile
import threading
import time
from types import SimpleNamespace

from functions.gui import runner as r
from functions.gui.bridge import UiBridge, ui


def make_runner(run_stage, debug_mode=False, minimal=False, on_event=None):
    tmp = tempfile.mkdtemp()
    events = []

    def post(kind, payload):
        events.append((kind, payload))
        if on_event:
            on_event(kind, payload)

    bridge = UiBridge(post, minimal=minimal)
    cfgs = SimpleNamespace(debug_mode=debug_mode, json_attr_dir=tmp)
    return r.PipelineRunner(bridge, lambda: cfgs, run_stage), bridge, events, tmp


def ends(events):
    return {p["name"]: p["status"] for k, p in events if k == "stage_end"}


def test_runs_in_order_and_writes_timing():
    calls = []
    runner, _, events, tmp = make_runner(lambda cfgs, name: calls.append(name))
    runner.start(["align", "refine"])
    runner.join(5)
    assert calls == ["align", "refine"]
    assert ends(events) == {"align": "done", "refine": "done"}
    assert events[-1] == ("run_end", None)
    with open(os.path.join(tmp, "timing.json"), encoding="utf-8") as f:
        timing = json.load(f)
    assert set(timing["stages"]) == {"align", "refine"} and timing["minimal"] is False


def test_failure_stops_the_run():
    calls = []

    def run_stage(cfgs, name):
        calls.append(name)
        if name == "refine":
            raise ValueError("boom")

    runner, _, events, _ = make_runner(run_stage)
    runner.start(["align", "refine", "decompose"])
    runner.join(5)
    assert calls == ["align", "refine"]
    end = [p for k, p in events if k == "stage_end"][-1]
    assert end["status"] == "failed" and "boom" in end["error"]


def test_stop_while_waiting_for_input():
    def run_stage(cfgs, name):
        ui().step("select")
        ui().interact("scene")

    def on_event(kind, payload):
        if kind == "scene":
            threading.Timer(0.05, bridge.request_stop).start()

    runner, bridge, events, _ = make_runner(run_stage, on_event=on_event)
    runner.start(["segment", "articulate"])
    runner.join(5)
    assert ends(events) == {"segment": "stopped"}


def test_stop_during_long_call_ends_at_next_step():
    def run_stage(cfgs, name):
        ui().step("native")
        time.sleep(0.2)  # stands in for CoACD / Poisson
        ui().step("save")

    runner, bridge, events, _ = make_runner(run_stage)
    runner.start(["decompose"])
    time.sleep(0.05)
    bridge.request_stop()
    runner.join(5)
    assert not runner.busy
    assert ends(events) == {"decompose": "stopped"}


def test_debug_follows_cfgs_and_minimal():
    seen = []
    runner, bridge, _, _ = make_runner(lambda c, n: seen.append(ui().debug), debug_mode=True)
    runner.start(["align"]); runner.join(5)
    runner2, _, _, _ = make_runner(lambda c, n: seen.append(ui().debug), debug_mode=True, minimal=True)
    runner2.start(["align"]); runner2.join(5)
    assert seen == [True, False]


def test_first_blocked_names_missing_upstream():
    assert r.first_blocked(["segment"], {}) == ("segment", ["refine", "decompose"])
    assert r.first_blocked(["align", "refine", "decompose"], {}) is None
    assert r.first_blocked(["decompose"], {"refine": {"dirs": {}}}) is None
    assert r.first_blocked(["align"], {}, restore_align=True) == ("align", ["transform"])


def test_statuses_helpers():
    states = {"transform": {"m": 1}, "refine": {"d": 1}}
    st = r.initial_statuses(states)
    assert st["align"] == "cached" and st["refine"] == "cached" and st["decompose"] == "pending"
    st.update(decompose="done", segment="done", bind="pending")
    after = r.stale_after(st, "refine")
    assert after["align"] == "cached" and after["refine"] == "cached"
    assert after["decompose"] == "stale" and after["segment"] == "stale" and after["bind"] == "pending"
    enabled = {"align": True, "refine": True, "decompose": False, "segment": True,
               "articulate": True, "bind": False}
    assert r.stages_from("decompose", enabled) == ["decompose", "segment", "articulate"]


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m tests.test_runner`
Expected: FAIL with `ImportError: cannot import name 'runner'`.

- [ ] **Step 3: Implement `functions/gui/runner.py`**

```python
"""Runs pipeline stages on a worker thread and reports through the UiBridge. Qt-free."""
import json
import os
import threading
import traceback
from datetime import datetime
from typing import Callable

from functions.gui.bridge import PipelineStopped, set_ui

STAGE_ORDER = ["align", "refine", "decompose", "segment", "articulate", "bind"]
STAGE_LABELS = {"align": "Align", "refine": "Refine", "decompose": "Decompose", "segment": "Segment",
                "articulate": "Articulate", "bind": "Bind"}
# states.json sections a stage reads, and the section it writes (bind writes only export files)
PREREQS = {"align": [], "refine": ["transform"], "decompose": ["refine"], "segment": ["refine", "decompose"],
           "articulate": ["refine", "segment"], "bind": ["transform", "refine", "segment"]}
PRODUCES = {"align": "transform", "refine": "refine", "decompose": "decompose", "segment": "segment",
            "articulate": "articulate", "bind": None}


def read_states(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def missing_prereqs(stage: str, available: set, restore_align: bool = False) -> list[str]:
    need = PREREQS[stage] + (["transform"] if stage == "align" and restore_align else [])
    return [k for k in need if k not in available]


def first_blocked(stages, states: dict, restore_align: bool = False):
    """(stage, missing sections) for the first stage whose inputs are neither in states.json nor
    produced earlier in this run; None when the run can start."""
    available = {k for k, v in states.items() if v}
    for stage in stages:
        missing = missing_prereqs(stage, available, restore_align)
        if missing:
            return stage, missing
        if PRODUCES[stage]:
            available.add(PRODUCES[stage])
    return None


def initial_statuses(states: dict) -> dict:
    return {s: "cached" if PRODUCES[s] and states.get(PRODUCES[s]) else "pending" for s in STAGE_ORDER}


def stale_after(statuses: dict, rerun: str) -> dict:
    """Finished stages downstream of `rerun` become 'stale'."""
    i = STAGE_ORDER.index(rerun)
    return {s: "stale" if STAGE_ORDER.index(s) > i and st in ("done", "cached") else st
            for s, st in statuses.items()}


def stages_from(stage: str, enabled: dict) -> list[str]:
    """`stage` itself plus every enabled stage after it."""
    i = STAGE_ORDER.index(stage)
    return [stage] + [s for s in STAGE_ORDER[i + 1:] if enabled.get(s)]


def write_timing(attr_dir: str, report: dict, started: str, minimal: bool) -> str:
    path = os.path.join(attr_dir, "timing.json")
    os.makedirs(attr_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"run_started": started, "minimal": minimal, "stages": report}, f, indent=2)
    return path


class PipelineRunner:
    """Runs stages on a daemon thread. make_cfgs() is called at every stage start, so each stage uses
    the parameters as they were when it started."""

    def __init__(self, bridge, make_cfgs: Callable, run_stage: Callable):
        self.bridge, self.make_cfgs, self.run_stage = bridge, make_cfgs, run_stage
        self._thread = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, stages) -> None:
        if self.busy:
            raise RuntimeError("A run is already active.")
        self.bridge.reset_stop()
        self._thread = threading.Thread(target=self._run, args=(list(stages),), daemon=True, name="pipeline")
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, stages) -> None:
        b = self.bridge
        set_ui(b)
        b.timer.reset()
        started = datetime.now().isoformat(timespec="seconds")
        cfgs = None
        try:
            for name in stages:
                b.begin_stage(name)
                try:
                    cfgs = self.make_cfgs()
                    b.debug = bool(cfgs.debug_mode) and not b.minimal
                    self.run_stage(cfgs, name)
                except PipelineStopped:
                    print(f"[info]: {name} stopped by the user.")
                    b.end_stage(name, "stopped")
                    break
                except Exception:
                    tb = traceback.format_exc()
                    print(tb)
                    b.end_stage(name, "failed", tb)
                    break
                b.end_stage(name, "done")
        finally:
            if cfgs is not None and b.timer.stages:
                print(b.timer.summary())
                write_timing(cfgs.json_attr_dir, b.timer.report(), started, b.minimal)
            b.post("run_end", None)
```

- [ ] **Step 4: Add the stage table to `functions/pipeline/interface.py`**

Change the config import to `from functions.utils.config import load_object, load_params` and the `SystemConfigs.obj` default to `field(default_factory=lambda: load_object())`. Delete `execute_pipeline` and the module-level `import time`. Add after `SystemConfigs`:

```python
from functions.gui.runner import STAGE_ORDER

STAGE_FUNCS = {
    "align": lambda cfgs: restore_transform(cfgs) if cfgs.restore_align else stage_transform(cfgs),
    "refine": lambda cfgs: stage_refine(cfgs, debug_mode=cfgs.debug_mode),
    "decompose": stage_decompose,
    "segment": stage_segment,
    "articulate": stage_articulate,
    "bind": stage_bind,
}
assert list(STAGE_FUNCS) == STAGE_ORDER


def run_stage(cfgs: SystemConfigs, name: str) -> None:
    """Run one stage. Progress, interaction and timing go through functions.gui.bridge.ui()."""
    STAGE_FUNCS[name](cfgs)
```

Replace the `__main__` block with (the GUI entry point arrives in Task 13):

```python
if __name__ == "__main__":
    from functions.gui.app import main
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m tests.test_runner && .venv/bin/python -c "from functions.pipeline.interface import run_stage, SystemConfigs; print(SystemConfigs().object_name)"`
Expected: `ok`, then the object name from `cfgs/object_cfg.yml`.

- [ ] **Step 6: Commit**

```bash
git add functions/gui/runner.py functions/pipeline/interface.py tests/test_runner.py
git commit -m "feat(gui): worker-thread pipeline runner with stage table

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Transform targets and interaction models

**Files:**
- Create: `functions/gui/manip.py`, `functions/gui/models.py`, `tests/test_manip.py`, `tests/test_models.py`

**Interfaces:**
- Consumes: `functions.math.geometry.normalize`, `rotmat(axis, theta_radians) -> 3x3`.
- Produces in `manip.py`: `KEY_BINDINGS: dict[str, (kind, axis, sign)]`, `KEY_HINTS: list[(keys, text)]`, `translation(v) -> 4x4`, `rotation(axis, deg, pivot=(0,0,0)) -> 4x4`, `key_delta(key, move_step, turn_deg, pivot) -> 4x4 | None`, `to_fields(matrix) -> (euler_xyz_deg, translation)`, `from_fields(euler_deg, trans) -> 4x4`, `Transformable` (Protocol: `pivot()`, `apply(delta)`), `AssemblyTarget(on_change=None)` (`matrix`, `pivot`, `apply`, `set_matrix`), `VectorGroupTarget(vectors, on_change=None)` (`vectors`, `pivot`, `apply`).
- Produces in `models.py`: `PartAssignment(n_fragments, parts_num)` (`owner`, `prev`, `mode`, `parts_num`, `set_mode`, `cycle_mode`, `assign`, `undo`, `counts`), `group_fragments(fragments, owner, parts_num)`, `NEXT_STATE`, `group_pairs(bicons) -> [((p, q), [bicon])]`, `valid_vectors(group) -> [(bicon, vector)]`, `cycle_state(vector, counter) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_manip.py`:

```python
import numpy as np
import vedo

from functions.gui.manip import (AssemblyTarget, VectorGroupTarget, from_fields, key_delta, rotation,
                                 to_fields, translation)
from functions.math.geometry import normalize, rotmat


def old_key(asm, k, angle, step):
    """Copy of the deleted transform.key_press_callback (reference behaviour)."""
    {"u": lambda: asm.rotate_z(-angle), "i": lambda: asm.rotate_z(angle),
     "h": lambda: asm.rotate_y(-angle), "j": lambda: asm.rotate_y(angle),
     "b": lambda: asm.rotate_x(-angle), "n": lambda: asm.rotate_x(angle),
     "w": lambda: asm.shift(step, 0, 0), "s": lambda: asm.shift(-step, 0, 0),
     "d": lambda: asm.shift(0, step, 0), "a": lambda: asm.shift(0, -step, 0),
     "space": lambda: asm.shift(0, 0, step), "z": lambda: asm.shift(0, 0, -step)}[k]()


def test_rotation_keeps_pivot_fixed():
    m = rotation([0, 0, 1], 37.0, pivot=[1.0, 2.0, 3.0])
    assert np.allclose(m @ [1.0, 2.0, 3.0, 1.0], [1.0, 2.0, 3.0, 1.0])
    assert np.allclose(translation([1, 2, 3])[:3, 3], [1, 2, 3])


def test_align_keys_match_old_vedo_assembly():
    asm = vedo.Assembly((vedo.Mesh([[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]]]),))
    target = AssemblyTarget()
    for key in ["u", "w", "i", "i", "space", "b", "d", "n", "h", "j", "s", "z", "a"]:
        target.apply(key_delta(key, 0.5, 1.0, target.pivot()))
        old_key(asm, key, 1.0, 0.5)
    assert np.allclose(target.matrix, asm.transform.matrix, atol=1e-9)
    assert key_delta("q", 0.5, 1.0, target.pivot()) is None


def test_set_matrix_and_fields_round_trip():
    seen = []
    target = AssemblyTarget(on_change=seen.append)
    goal = from_fields([10.0, -20.0, 30.0], [0.1, 0.2, 0.3])
    target.set_matrix(goal)
    assert np.allclose(target.matrix, goal) and len(seen) == 1
    euler, trans = to_fields(target.matrix)
    assert np.allclose(euler, [10.0, -20.0, 30.0]) and np.allclose(trans, [0.1, 0.2, 0.3])


def test_vector_group_matches_old_key_handler():
    vectors = [{"center": [0.0, 0.0, 0.0], "n": [1.0, 0.0, 0.0]},
               {"center": [1.0, 1.0, 0.0], "n": [0.0, 1.0, 0.0]}]
    expected = [dict(v) for v in vectors]
    target = VectorGroupTarget(vectors)
    th = np.deg2rad(1.5)
    for key in ["w", "i", "i", "space", "n"]:
        target.apply(key_delta(key, 0.1, 1.5, target.pivot()))
        d = {"w": (0.1, 0, 0), "space": (0, 0, 0.1)}.get(key, (0, 0, 0))
        R = {"i": rotmat([0, 0, 1], th), "n": rotmat([1, 0, 0], th)}.get(key)
        for v in expected:  # old select_joint_vectors.on_key
            v["center"] = (np.asarray(v["center"]) + d).tolist()
            if R is not None:
                v["n"] = normalize(R @ normalize(v["n"])).tolist()
    for got, want in zip(vectors, expected):
        assert np.allclose(got["center"], want["center"]) and np.allclose(got["n"], want["n"])


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
```

Create `tests/test_models.py`:

```python
from functions.gui.models import (PartAssignment, cycle_state, group_fragments, group_pairs,
                                  valid_vectors)


def test_part_assignment():
    m = PartAssignment(n_fragments=3, parts_num=2)
    assert m.owner == [0, 1, 1, 1] and m.mode == 0
    assert not m.assign(2)              # view mode ignores clicks
    assert m.cycle_mode() == 1 and m.cycle_mode() == 2 and m.cycle_mode() == 0
    m.set_mode(2)
    assert m.assign(2) and m.owner[2] == 2
    assert m.counts() == {1: 2, 2: 1}
    assert m.undo(2) and m.owner[2] == 1
    m.set_mode(9)
    assert m.mode == 2
    assert group_fragments(["f1", "f2", "f3"], [0, 1, 2, 1], 2) == [[], ["f1", "f3"], ["f2"]]


def test_group_pairs_skips_zero_pair_and_keeps_order():
    bicons = [{"a": {"src": 2, "dst": 1}}, {"a": {"src": 0, "dst": 0}}, {"a": {"src": 1, "dst": 2}},
              {"a": {"src": 3, "dst": 1}}]
    pairs = group_pairs(bicons)
    assert [k for k, _ in pairs] == [(1, 2), (1, 3)]
    assert len(pairs[0][1]) == 2
    assert group_pairs([{"a": {"src": 0, "dst": 0}}]) == []


def test_valid_vectors_skips_bad_normals_and_fills_center():
    good = {"n": [0, 0, 1]}
    bicon = {"center": [1.0, 2.0, 3.0],
             "vectors": [good, {"n": [float("nan"), 0, 0]}, {"n": [0, 0, 0]}, {"center": [0, 0, 0]}]}
    out = valid_vectors([bicon, {"vectors": None}])
    assert out == [(bicon, good)] and good["center"] == [1.0, 2.0, 3.0]


def test_cycle_state_orders_revolute_picks():
    counter = [0]
    a, b = {}, {"state": "Prismatic", "order": 4}
    assert cycle_state(a, counter) == "Revolute" and a["order"] == 1
    assert cycle_state(a, counter) == "Prismatic" and a["order"] == 1
    assert cycle_state(a, counter) == "None" and a["order"] is None
    assert cycle_state(b, counter) == "None" and b["order"] is None
    assert cycle_state(b, counter) == "Revolute" and b["order"] == 2


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m tests.test_manip; .venv/bin/python -m tests.test_models`
Expected: both FAIL with `ModuleNotFoundError` for `functions.gui.manip` / `functions.gui.models`.

- [ ] **Step 3: Implement `functions/gui/manip.py`**

```python
"""Rigid 4x4 deltas and the targets they move. Keyboard keys, panel fields, and the gizmo all build a
delta with these helpers and hand it to a Transformable, so a new input or a new target plugs in
without touching the others (e.g. a future SingleVectorTarget for per-arrow mouse control)."""
from typing import Callable, Protocol

import numpy as np
from scipy.spatial.transform import Rotation

from functions.math.geometry import normalize, rotmat

AXES = np.eye(3)

# key -> (kind, axis index, sign); shared by Align and Articulate
KEY_BINDINGS = {
    "w": ("move", 0, +1), "s": ("move", 0, -1),
    "d": ("move", 1, +1), "a": ("move", 1, -1),
    "space": ("move", 2, +1), "z": ("move", 2, -1),
    "n": ("turn", 0, +1), "b": ("turn", 0, -1),
    "j": ("turn", 1, +1), "h": ("turn", 1, -1),
    "i": ("turn", 2, +1), "u": ("turn", 2, -1),
}
KEY_HINTS = [("W/S", "move ±X"), ("D/A", "move ±Y"), ("Space/Z", "move ±Z"),
             ("N/B", "rotate ±X"), ("J/H", "rotate ±Y"), ("I/U", "rotate ±Z")]


def translation(v) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = np.asarray(v, dtype=float)
    return m


def rotation(axis, deg: float, pivot=(0.0, 0.0, 0.0)) -> np.ndarray:
    """Right-handed rotation by `deg` degrees about `axis` through `pivot`."""
    r = rotmat(axis, np.deg2rad(deg))
    p = np.asarray(pivot, dtype=float)
    m = np.eye(4)
    m[:3, :3] = r
    m[:3, 3] = p - r @ p
    return m


def key_delta(key: str, move_step: float, turn_deg: float, pivot) -> np.ndarray | None:
    """Delta for a bound key, or None for any other key."""
    if key not in KEY_BINDINGS:
        return None
    kind, axis, sign = KEY_BINDINGS[key]
    if kind == "move":
        return translation(AXES[axis] * sign * move_step)
    return rotation(AXES[axis], sign * turn_deg, pivot)


def to_fields(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(extrinsic xyz Euler angles in degrees, translation) for the panel fields."""
    euler = Rotation.from_matrix(matrix[:3, :3]).as_euler("xyz", degrees=True)
    return euler, matrix[:3, 3].copy()


def from_fields(euler_deg, trans) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = Rotation.from_euler("xyz", euler_deg, degrees=True).as_matrix()
    m[:3, 3] = trans
    return m


class Transformable(Protocol):
    def pivot(self) -> np.ndarray: ...

    def apply(self, delta: np.ndarray) -> None: ...


class AssemblyTarget:
    """Align: the accumulated world matrix of the mesh. Rotations pivot on the world origin so the
    ground plane (z = 0) and the axes stay put while the object turns."""

    def __init__(self, on_change: Callable[[np.ndarray], None] | None = None):
        self.matrix = np.eye(4)
        self.on_change = on_change

    def pivot(self) -> np.ndarray:
        return np.zeros(3)

    def apply(self, delta: np.ndarray) -> None:
        self.matrix = delta @ self.matrix
        if self.on_change:
            self.on_change(delta)

    def set_matrix(self, matrix: np.ndarray) -> None:
        """Jump to an absolute matrix (panel fields, Reset) by applying the difference as one delta."""
        self.apply(np.asarray(matrix, dtype=float) @ np.linalg.inv(self.matrix))


class VectorGroupTarget:
    """Articulate: every candidate vector of one part pair (dicts with 'center' and 'n', edited in place).
    Translation shifts every center; rotation turns every n, so each arrow rotates about its own center
    (the old key behaviour). The gizmo sits at the mean center."""

    def __init__(self, vectors: list[dict], on_change: Callable[[np.ndarray], None] | None = None):
        self.vectors = vectors
        self.on_change = on_change

    def pivot(self) -> np.ndarray:
        if not self.vectors:
            return np.zeros(3)
        return np.mean([np.asarray(v["center"], dtype=float) for v in self.vectors], axis=0)

    def apply(self, delta: np.ndarray) -> None:
        p = self.pivot()
        shift = delta[:3, :3] @ p + delta[:3, 3] - p  # zero for a rotation about the pivot
        for v in self.vectors:
            v["center"] = (np.asarray(v["center"], dtype=float) + shift).tolist()
            v["n"] = normalize(delta[:3, :3] @ normalize(v["n"])).tolist()
        if self.on_change:
            self.on_change(delta)
```

- [ ] **Step 4: Implement `functions/gui/models.py`**

```python
"""Pure interaction state for the Segment and Articulate scenes (no Qt/VTK)."""
from collections import defaultdict

import numpy as np


class PartAssignment:
    """Fragment -> part ownership. Fragments are 1-based; owner[0] is an unused slot.
    Mode 0 is view-only. In mode k, assign() moves a fragment to part k and undo() reverts that
    fragment's last assignment."""

    def __init__(self, n_fragments: int, parts_num: int):
        self.parts_num = parts_num
        self.owner = [0] + [1] * n_fragments
        self.prev = list(self.owner)
        self.mode = 0

    def set_mode(self, mode: int) -> None:
        self.mode = max(0, min(int(mode), self.parts_num))

    def cycle_mode(self) -> int:
        self.mode = (self.mode + 1) % (self.parts_num + 1)
        return self.mode

    def assign(self, i: int) -> bool:
        if self.mode == 0:
            return False
        self.prev[i], self.owner[i] = self.owner[i], self.mode
        return True

    def undo(self, i: int) -> bool:
        if self.mode == 0:
            return False
        self.owner[i] = self.prev[i]
        return True

    def counts(self) -> dict[int, int]:
        return {p: self.owner[1:].count(p) for p in range(1, self.parts_num + 1)}


def group_fragments(fragments, owner, parts_num: int) -> list[list]:
    """parts[0..parts_num] (lists of fragments) from an owner list."""
    parts = [[] for _ in range(parts_num + 1)]
    for i, fragment in enumerate(fragments, start=1):
        parts[owner[i]].append(fragment)
    return parts


NEXT_STATE = {"None": "Revolute", "Revolute": "Prismatic"}  # anything else -> "None"


def group_pairs(bicons) -> list[tuple[tuple[int, int], list[dict]]]:
    """Bicons grouped by unordered part pair (p <= q) in first-seen order; the (0, 0) pair is skipped."""
    pairs = defaultdict(list)
    for bicon in bicons:
        p, q = int(bicon["a"]["src"]), int(bicon["a"]["dst"])
        pairs[(min(p, q), max(p, q))].append(bicon)
    return [(k, v) for k, v in pairs.items() if k != (0, 0)]


def valid_vectors(group) -> list[tuple[dict, dict]]:
    """(bicon, vector) for every vector with a finite, non-zero `n`; a missing `center` is filled from
    the bicon so the vector can be moved."""
    out = []
    for bicon in group:
        for v in bicon.get("vectors") or []:
            if v.get("n") is None:
                continue
            n = np.asarray(v["n"], dtype=float)
            if not np.isfinite(n).all() or np.linalg.norm(n) < 1e-12:
                continue
            v.setdefault("center", [float(c) for c in bicon.get("center", [0.0, 0.0, 0.0])])
            out.append((bicon, v))
    return out


def cycle_state(vector: dict, counter: list[int]) -> str:
    """None -> Revolute -> Prismatic -> None. Each Revolute pick gets the next per-pair `order`."""
    state = NEXT_STATE.get(vector.get("state", "None"), "None")
    vector["state"] = state
    if state == "Revolute":
        counter[0] += 1
        vector["order"] = counter[0]
    elif state == "None":
        vector["order"] = None
    return state
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m tests.test_manip && .venv/bin/python -m tests.test_models`
Expected: `ok` twice.

- [ ] **Step 6: Commit**

```bash
git add functions/gui/manip.py functions/gui/models.py tests/test_manip.py tests/test_models.py
git commit -m "feat(gui): transform targets and pure interaction models

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: View cube

**Files:**
- Create: `functions/gui/viewcube.py`, `tests/test_view_math.py`

**Interfaces:**
- Consumes: `theme.current()`, `theme.rgb` (Task 3).
- Produces: `FACES`, `HOME = (1, 1, 1)`, `SIZE_PX = 110`, `piece_at(point, half=0.5, band=0.6) -> tuple | None`, `view_for(piece) -> (direction, view_up)`, `slerp(a, b, t) -> unit vector`, `ViewCube(main_renderer, render_window, request_render, dpr=1.0)` with `contains(x, y)`, `on_move(x, y) -> bool`, `on_press(x, y) -> bool`, `snap(piece, duration_ms=200)`, `set_view(piece)`, `set_theme(t)`, `sync()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_view_math.py`:

```python
import numpy as np

from functions.gui.viewcube import piece_at, slerp, view_for


def test_piece_at_face_edge_corner():
    assert piece_at([0.5, 0.0, 0.1]) == (1, 0, 0)
    assert piece_at([0.5, 0.45, 0.0]) == (1, 1, 0)
    assert piece_at([-0.5, -0.45, 0.48]) == (-1, -1, 1)
    assert piece_at([0.0, 0.0, 0.0]) is None


def test_view_for_up_vectors():
    d, up = view_for((0, 0, 1))
    assert np.allclose(d, [0, 0, 1]) and np.allclose(up, [-1, 0, 0])
    d, up = view_for((0, 0, -1))
    assert np.allclose(up, [1, 0, 0])
    d, up = view_for((1, 1, 0))
    assert np.allclose(d, np.array([1, 1, 0]) / np.sqrt(2)) and np.allclose(up, [0, 0, 1])


def test_slerp_endpoints_and_antipodes():
    a, b = np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    assert np.allclose(slerp(a, b, 0.0), a) and np.allclose(slerp(a, b, 1.0), b)
    assert np.isclose(np.linalg.norm(slerp(a, b, 0.3)), 1.0)
    mid = slerp(a, -a, 0.5)
    assert np.isclose(np.linalg.norm(mid), 1.0) and abs(np.dot(mid, a)) < 1e-6
    assert np.allclose(slerp(a, -a, 1.0), -a)


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m tests.test_view_math`
Expected: FAIL with `ModuleNotFoundError: No module named 'functions.gui.viewcube'`.

- [ ] **Step 3: Implement `functions/gui/viewcube.py`**

```python
"""Corner navigation cube. Clicking a face looks straight at it, an edge looks at its two faces at 45°,
a corner gives the isometric view of its three faces. Z is up and Front is +X (URDF); side labels
follow the viewer as in CAD cubes (looking at Front, +Y is Right)."""
import numpy as np
from PySide6.QtCore import QTimer
from vtkmodules.vtkFiltersSources import vtkCubeSource
from vtkmodules.vtkRenderingAnnotation import vtkAnnotatedCubeActor
from vtkmodules.vtkRenderingCore import vtkActor, vtkCellPicker, vtkPolyDataMapper, vtkRenderer

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
        self.cube.TextEdgesOff()
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

        self.picker = vtkCellPicker()
        self.picker.SetTolerance(0.0005)
        self._hover = None
        self._timer = None
        self.set_theme(th.current())
        main_renderer.AddObserver("StartEvent", self.sync)

    def set_theme(self, t) -> None:
        self.cube.GetCubeProperty().SetColor(*th.rgb(t.button))
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

    def _pick(self, x, y):
        if not self.contains(x, y) or not self.picker.Pick(x, y, 0, self.ren):
            return None
        return piece_at(self.picker.GetPickPosition())

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m tests.test_view_math`
Expected: `ok`. (The `ViewCube` class is exercised visually in Task 9.)

- [ ] **Step 5: Commit**

```bash
git add functions/gui/viewcube.py tests/test_view_math.py
git commit -m "feat(gui): corner view cube with face/edge/corner snapping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Transform gizmo

**Files:**
- Create: `functions/gui/gizmo.py`
- Modify: `tests/test_view_math.py` (add gizmo math tests above the `__main__` block)

**Interfaces:**
- Consumes: `manip.rotation`, `manip.translation`, `Transformable` (Task 6); `theme` (Task 3).
- Produces: `axis_drag_distance(d, p_scr, q_scr, length) -> float`, `ring_drag_angle(m0, m1, c) -> float` (degrees, counter-clockwise positive), `world_to_display(renderer, p) -> np.ndarray`, `TransformGizmo(main_renderer, render_window, on_delta, request_render)` with `attach(target)`, `detach()`, `toggle()`, `set_theme(t)`, `sync()`, `on_press(x, y) -> bool`, `on_move(x, y) -> bool`, `on_release() -> bool`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_view_math.py`, after the existing imports:

```python
from functions.gui.gizmo import axis_drag_distance, ring_drag_angle
```

and before the `__main__` block:

```python
def test_axis_drag_distance():
    # axis drawn 100 px to the right for a world segment of length 2
    assert np.isclose(axis_drag_distance([50, 0], [0, 0], [100, 0], 2.0), 1.0)
    assert np.isclose(axis_drag_distance([0, 40], [0, 0], [100, 0], 2.0), 0.0)
    assert np.isclose(axis_drag_distance([-25, 10], [0, 0], [100, 0], 2.0), -0.5)
    assert axis_drag_distance([10, 10], [5, 5], [5, 5], 1.0) == 0.0  # axis points at the camera


def test_ring_drag_angle():
    c = np.array([0.0, 0.0])
    assert np.isclose(ring_drag_angle([10, 0], [0, 10], c), 90.0)
    assert np.isclose(ring_drag_angle([0, 10], [10, 0], c), -90.0)
    assert ring_drag_angle([1, 0], [0, 10], c) == 0.0  # too close to the center
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m tests.test_view_math`
Expected: FAIL with `ModuleNotFoundError: No module named 'functions.gui.gizmo'`.

- [ ] **Step 3: Implement `functions/gui/gizmo.py`**

Before writing, confirm the vedo shape signatures: `.venv/bin/python -c "import vedo, inspect; print(inspect.signature(vedo.Arrow)); print(inspect.signature(vedo.Torus))"`. Expected: `Arrow(start_pt, end_pt, s, shaft_radius, head_radius, head_length, res, c, alpha)` and `Torus(pos, r1, r2, res, quads, c, alpha)`; adapt keyword names only if they differ.

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m tests.test_view_math`
Expected: `ok`. (The `TransformGizmo` class is exercised visually in Task 9.)

- [ ] **Step 5: Commit**

```bash
git add functions/gui/gizmo.py tests/test_view_math.py
git commit -m "feat(gui): always-on-top transform gizmo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Viewport (embedded plotter, event router, overlays)

**Files:**
- Create: `functions/gui/viewport.py`

**Interfaces:**
- Consumes: `ViewCube`, `HOME` (Task 7); `TransformGizmo` (Task 8); `theme` (Task 3); `AssemblyTarget` (Task 6, demo only).
- Scene duck type the viewport calls (implemented by `Scene` in Task 10): attributes `title`, `hint`, `controls`, `target` (Transformable or None); methods `build() -> list`, `apply(delta)`, `on_key(key) -> bool`, `on_pick(actor, button)`, `on_enter()`, `on_theme()`; the viewport sets `scene.viewport = self`.
- Produces: `Viewport(QWidget)` with attributes `plt`, `renderer`, `gizmo`, `cube`, `scene`, and methods `mount(scene)`, `unmount()`, `set_actors(actors)`, `refresh_overlays()`, `render()`, `reset_view()`, `suspend(on)`, `apply_theme(t)`, `close_vtk()`. Key names passed to scenes are lowercase (`"tab"`, `"space"`, `"enter"`, letters).

- [ ] **Step 1: Implement `functions/gui/viewport.py`**

```python
"""The single 3D viewport: one vedo.Plotter embedded in Qt, scene mounting, text overlays, the view
cube, the transform gizmo, and one mouse/key router (view cube -> gizmo -> scene -> camera)."""
import sys

import vtkmodules.qt

vtkmodules.qt.PyQtImpl = "PySide6"  # must be set before importing QVTKRenderWindowInteractor

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
            text = f"{s.title}\n{s.hint}" if s.hint else s.title
            self.overlays.append(vedo.Text2D(text, pos="top-left", s=0.85, c=t.text, bg=t.panel,
                                             alpha=0.85, font="Arial"))
        if s is not None and s.controls:
            items = [f"{k}  {v}" for k, v in s.controls]
            rows = ["     ".join(items[i:i + HINTS_PER_ROW]) for i in range(0, len(items), HINTS_PER_ROW)]
            self.overlays.append(vedo.Text2D("\n".join(rows), pos="bottom-left", s=0.75, c=t.text2,
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
```

- [ ] **Step 2: Smoke-run the demo**

Run: `.venv/bin/python -m functions.gui.viewport --smoke`
Expected: a window opens for about 1.5 s showing a cube on a grid, a gizmo at the origin, and the view cube in the top-right corner; the process exits with code 0 and no traceback.

If the window is blank or crashes on macOS, set `vtkmodules.qt.QVTKRWIBase = "QOpenGLWidget"` next to `PyQtImpl` and rerun; keep whichever works and note it in a comment.

- [ ] **Step 3: Manual check (interactive run without `--smoke`)**

Run: `.venv/bin/python -m functions.gui.viewport`
Check, then close the window:
1. Click the cube's "Front" face: the camera turns to look along −X with Z up. Click the Front/Top edge: a 45° view. Click a corner: an isometric view.
2. Drag the red arrow: the cube moves along X. Drag the blue ring: the cube turns about Z. The camera does not rotate during gizmo drags.
3. Hover a handle: it turns white. `G` hides/shows the gizmo; `R` resets the view; `Enter` prints the matrix.

- [ ] **Step 4: Commit**

```bash
git add functions/gui/viewport.py
git commit -m "feat(gui): Qt-embedded viewport with view cube and gizmo routing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Scenes

**Files:**
- Create: `functions/gui/scenes.py`

**Interfaces:**
- Consumes: `Viewport` (Task 9); `manip` (Task 6); `models` (Task 6); `theme` (Task 3); `functions.visualize.style` (`arrow_params`, `label_colors`, `pastel_hex`, `state_arrow`); `functions.math.geometry.normalize`.
- Produces:
  - `Scene` base: attributes `title`, `hint`, `controls`, `target`, `move_step`, `turn_deg`, `viewport`, `finish` (callable set by the window); methods `build()`, `widget()`, `on_key(key)`, `apply(delta)`, `on_change()`, `on_pick(actor, button)`, `on_enter()`, `on_theme()`, `result()`.
  - `CheckpointScene(title, build_fn)` → result `None`.
  - `AlignScene(verts, faces, point_colors=None, cell_colors=None)` → result: fine 4×4 `np.ndarray`.
  - `PartSelectScene(fragments, verts, faces, parts_num)` with `fragments = [(vertices, faces), ...]` → result: owner `list[int]` (index 0 unused).
  - `JointSelectScene(bicons, verts, faces, vert_label)` → edits `bicons` in place; result `None`.
  - Helpers `button(text, on_click)`, `primary_button(text, on_click)`, `section(text)`.

- [ ] **Step 1: Implement `functions/gui/scenes.py`**

```python
"""Scenes mounted in the single viewport. A scene is constructed on the worker thread from plain data
only; build() and widget() run on the GUI thread, where every vedo and Qt object is created."""
import sys

import numpy as np
import vedo
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from functions.gui import theme as th
from functions.gui.manip import (KEY_HINTS, AssemblyTarget, VectorGroupTarget, from_fields, key_delta,
                                 to_fields)
from functions.gui.models import PartAssignment, cycle_state, group_pairs, valid_vectors
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
    return layout


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

    def on_pick(self, actor, button: str) -> None:
        pass

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
    controls = KEY_HINTS + [("G", "gizmo"), ("R", "reset view"), ("Enter", "done")]
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

    def on_pick(self, actor, button: str) -> None:
        i = self.index.get(actor)
        if i is None:
            return
        changed = self.model.assign(i) if button == "left" else self.model.undo(i)
        if changed:
            self._refresh()

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
    controls = [("Click arrow", "cycle type")] + KEY_HINTS + [("G", "gizmo"), ("R", "reset view"),
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
        self.pair_label = self.counts_label = None
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

    def on_pick(self, actor, button: str) -> None:
        v = self.arrows.get(actor)
        if v is None or button != "left":
            return
        cycle_state(v, self.counters[self.i])
        self._redraw_arrows()
        self._render()

    def _go(self, step: int) -> None:
        if not self.pairs or self.viewport is None:
            return
        self._select_pair((self.i + step) % len(self.pairs))
        self.viewport.set_actors(self.build())
        self.viewport.gizmo.attach(self.target)
        self.viewport.refresh_overlays()
        self._update_labels()
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
        layout.addWidget(self.pair_label)
        layout.addWidget(self.counts_label)
        legend = QHBoxLayout()
        t = th.current()
        for name, color in (("Revolute", t.revolute), ("Prismatic", t.prismatic), ("None", t.none)):
            swatch = QLabel()
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(f"background: {color}; border-radius: 2px;")
            legend.addWidget(swatch)
            legend.addWidget(QLabel(name))
        legend.addStretch()
        layout.addLayout(legend)
        layout.addLayout(self._footer("Next pair", extra=[button("◂ Prev", lambda: self._go(-1))]))
        self._update_labels()
        return w

    def _update_labels(self) -> None:
        if self.pair_label is None:
            return
        if not self.pairs:
            self.pair_label.setText("No part pairs to review.")
            self.counts_label.setText("")
            self.primary.setText("Done ▸")
            return
        (p, q), _ = self.pairs[self.i]
        states = [v.get("state", "None") for _, v in self.items[self.i]]
        self.pair_label.setText(f"Parts {p} ↔ {q} · {self.i + 1} / {len(self.pairs)}")
        self.counts_label.setText(f"Revolute {states.count('Revolute')} · Prismatic {states.count('Prismatic')}"
                                  f" · {len(states)} candidates")
        self.primary.setText("Done ▸" if self.i == len(self.pairs) - 1 else "Next pair ▸")

    def on_theme(self) -> None:
        self._redraw_arrows()


if __name__ == "__main__":
    # Manual check: `.venv/bin/python -m functions.gui.scenes align|parts|joints [--smoke]`
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
```

- [ ] **Step 2: Smoke-run all three scenes**

Run: `for k in align parts joints; do .venv/bin/python -m functions.gui.scenes $k --smoke || break; done`
Expected: three windows open and close in turn, with no traceback.

- [ ] **Step 3: Manual check (interactive runs without `--smoke`)**

1. `align`: `W` moves the box +X and the panel's Move X field follows; typing 90 in Rotate Z turns the box; Reset returns it; `Enter` prints a 4×4 matrix.
2. `parts`: View mode shows both halves in part colors; `Tab` → Part 1 mutes Part 2; clicking a half in Part 2 mode moves it (chip counts update); a right click reverts it; Done prints `[0, ...]`.
3. `joints`: arrows are gray; clicking one turns it amber (Revolute) then blue (Prismatic); `W` moves all arrows of the pair; Next pair switches the mesh coloring and title; on the last pair the button reads "Done ▸".

- [ ] **Step 4: Commit**

```bash
git add functions/gui/scenes.py
git commit -m "feat(gui): checkpoint, align, part-selection and joint-selection scenes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Side panel widgets — Timeline, InteractionHost, LogView

**Files:**
- Create: `functions/gui/panel.py` (this task: timeline, interaction host, log; Task 12 adds `ParamEditor`), `tests/test_panel.py`

**Interfaces:**
- Consumes: `STAGE_ORDER`, `STAGE_LABELS` (Task 5); `theme` (Task 3); `scenes.section` (Task 10).
- Produces:
  - `Timeline(QWidget)`: signals `rerun(str)`, `run_from(str)`, `toggled(str, bool)`, `selected(str)`; methods `reset(statuses, enabled)`, `set_status(stage, status)`, `add_plan(stage, steps)`, `set_step(stage, key, state, meta="")`, `current_step(stage) -> str | None`, `finish(stage, status, compute, closed)`, `set_busy(busy)`; attribute `rows: dict[str, StageRow]`.
  - `StageRow`: `status`, `expanded`, `subs: dict[key, SubStepRow]`, `summary` (QLabel).
  - `InteractionHost(QWidget)`: `set_widget(widget)`, `set_idle(text)`.
  - `LogView(QWidget)`: `append(text)`, `set_expanded(on)`, `last` (QLabel).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_panel.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from functions.gui.panel import InteractionHost, LogView, Timeline  # noqa: E402
from functions.gui.runner import STAGE_ORDER  # noqa: E402

app = QApplication.instance() or QApplication([])


def test_timeline_flow():
    tl = Timeline()
    tl.reset({s: "pending" for s in STAGE_ORDER} | {"align": "cached"}, {s: True for s in STAGE_ORDER})
    assert tl.rows["align"].status == "cached"
    tl.set_status("refine", "running")
    assert tl.rows["refine"].expanded
    tl.add_plan("refine", [("cleaning", "① Cleaning", True), ("poisson", "② Poisson", False),
                           ("save", "Save", True)])
    tl.add_plan("refine", [("save", "Save", True), ("extra", "Extra", True)])  # appends unseen keys only
    assert list(tl.rows["refine"].subs) == ["cleaning", "poisson", "save", "extra"]
    assert tl.rows["refine"].subs["poisson"].state == "skipped"
    tl.set_step("refine", "cleaning", "running")
    assert tl.current_step("refine") == "cleaning"
    tl.set_step("refine", "cleaning", "done", "0.4s")
    tl.set_step("refine", "save", "running")
    tl.finish("refine", "done", 1.5, ("save", 1.1))
    row = tl.rows["refine"]
    assert row.status == "done" and not row.expanded
    assert row.subs["save"].state == "done"
    assert row.summary.text() == "2/3 · 1.5s"


def test_timeline_signals_and_busy():
    tl = Timeline()
    tl.reset({s: "done" for s in STAGE_ORDER}, {s: True for s in STAGE_ORDER})
    got = []
    tl.rerun.connect(lambda s: got.append(("rerun", s)))
    tl.toggled.connect(lambda s, on: got.append(("toggled", s, on)))
    tl.rows["segment"]._show_actions(True)  # hover state: actions are enabled only on hover
    tl.rows["segment"].rerun_btn.click()
    tl.rows["bind"].check.setChecked(False)
    assert got == [("rerun", "segment"), ("toggled", "bind", False)]
    tl.set_busy(True)
    assert not tl.rows["segment"].rerun_btn.isEnabled()


def test_interaction_host_and_log():
    host = InteractionHost()
    host.set_widget(QLabel("scene"))
    assert host.idle.isHidden()
    host.set_idle("Computing…")
    assert not host.idle.isHidden() and host.idle.text() == "Computing…"
    log = LogView()
    log.append("[info] one\n[info] two\n")
    assert log.last.text() == "[info] two"
    log.append("partial")
    assert log.last.text() == "partial"


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m tests.test_panel`
Expected: FAIL with `ModuleNotFoundError: No module named 'functions.gui.panel'`.

- [ ] **Step 3: Implement the widgets in `functions/gui/panel.py`**

```python
"""Side panel widgets: git-log style stage timeline, interaction host, parameter editor, and log."""
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QPainter, QPen, QColor
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
        self.check.toggled.connect(lambda on: self.toggled.emit(self.stage, on))
        self.dot = _label(name="Dot")
        self.name = _label(STAGE_LABELS[stage], "StageName")
        self.summary = _label("", "Meta")
        self.rerun_btn = QToolButton(text="↻", toolTip="Re-run this stage")
        self.from_btn = QToolButton(text="▶", toolTip="Run from this stage")
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
        self.rerun_btn.setEnabled(not busy)
        self.from_btn.setEnabled(not busy)
        if busy:
            self._show_actions(False)

    def _show_actions(self, on: bool) -> None:
        # keep the space reserved so the summary does not jump on hover
        for b in (self.rerun_btn, self.from_btn):
            b.setText(("↻" if b is self.rerun_btn else "▶") if on else "")
            b.setEnabled(on and not self.busy)

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
        if not rows:
            return
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m tests.test_panel`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add functions/gui/panel.py tests/test_panel.py
git commit -m "feat(gui): timeline, interaction host and log panel widgets

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Parameter editor

**Files:**
- Modify: `functions/gui/panel.py` (append `Collapsible`, `ParamEditor`), `tests/test_panel.py` (add editor tests)

**Interfaces:**
- Consumes: `params_io.field_kind`, `params_io.STAGE_SECTIONS` (Task 2); `config.load_object`, `config.load_params` (Task 1).
- Produces: `ParamEditor(QWidget)` with signals `changed()`, `object_changed(dict)`, `save_requested()`; methods `load(obj, params, comments, profiles)`, `values() -> (obj, params)` (deep copies), `modified() -> bool`, `set_stage_enabled(stage, on)`, `show_stage(stage)`, `set_busy(busy)`, `after_save(obj, profiles)`, `revert()`; attribute `widgets: dict[tuple, QWidget]` keyed by `("obj" | "params", *path)`. Stage → section map `SECTION_FOR_STAGE`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_panel.py` (imports at the top, tests above the `__main__` block):

```python
from functions.gui.panel import ParamEditor  # noqa: E402
from functions.gui.params_io import load_comments  # noqa: E402
from functions.utils.config import load_object, load_params  # noqa: E402


def make_editor():
    editor = ParamEditor()
    editor.load(load_object(""), load_params(object_profile=""), load_comments(), ["toy_20261020_143012"])
    return editor


def test_editor_edits_values_and_marks_modified():
    editor = make_editor()
    changed = []
    editor.changed.connect(lambda: changed.append(1))
    box = editor.widgets[("params", "decompose", "coacd", "threshold")]
    box.setText("0.2")
    box.editingFinished.emit()
    obj, params = editor.values()
    assert params["decompose"]["coacd"]["threshold"] == 0.2 and changed and editor.modified()
    assert editor.sections["decompose"].modified
    editor.revert()
    assert not editor.modified()
    assert editor.values()[1]["decompose"]["coacd"]["threshold"] != 0.2


def test_editor_kinds_and_object_reload_signal():
    editor = make_editor()
    assert type(editor.widgets[("params", "refine", "method")]).__name__ == "QComboBox"
    assert type(editor.widgets[("params", "transform", "use_auto_alignment")]).__name__ == "QCheckBox"
    pct = editor.widgets[("params", "refine", "pymeshlab", "params", "meshing_isotropic_explicit_remeshing",
                          "targetlen")]
    pct.setText("abc")
    pct.editingFinished.emit()
    assert editor.values()[1]["refine"]["pymeshlab"]["params"]["meshing_isotropic_explicit_remeshing"][
        "targetlen"] == "1%"  # invalid text is rejected
    reloads = []
    editor.object_changed.connect(reloads.append)
    combo = editor.widgets[("obj", "object_profile")]
    combo.setCurrentIndex(combo.findText("toy_20261020_143012"))
    assert reloads and reloads[-1]["object_profile"] == "toy_20261020_143012"
    assert ("obj", "parts", "num") in editor.widgets  # parts.num lives in the Segment section
    editor.set_stage_enabled("bind", False)
    assert editor.values()[1]["pipeline"]["stages"]["bind"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m tests.test_panel`
Expected: FAIL with `ImportError: cannot import name 'ParamEditor'`.

- [ ] **Step 3: Append the editor to `functions/gui/panel.py`**

Add to the imports at the top of `panel.py`:

```python
import copy

import yaml
from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QDoubleValidator, QRegularExpressionValidator
from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton, QScrollArea, QSpinBox

from functions.gui.params_io import STAGE_SECTIONS, field_kind
```

Append:

```python
SECTION_FOR_STAGE = {"align": "transform", "refine": "refine", "decompose": "decompose",
                     "segment": "segment", "articulate": "articulate", "bind": "bind"}
SECTION_TITLES = {"object": "Object", "pipeline": "Pipeline · run settings (not saved)", "transform": "Align",
                  "refine": "Refine", "decompose": "Decompose", "segment": "Segment",
                  "articulate": "Articulate", "bind": "Bind", "visualization": "Visualization"}
RELOAD_KEYS = {"object_name", "profile", "object_profile"}   # editing these reloads the parameters
NONE_PROFILE = "(none)"


class Collapsible(QWidget):
    """Header button + body; the header shows ● when anything inside was edited."""

    def __init__(self, title: str, level: int = 0):
        super().__init__()
        self.title = title
        self.modified = False
        self.head = QToolButton()
        self.head.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.head.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.head.clicked.connect(lambda: self.set_expanded(not self.body.isVisible()))
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

    def set_expanded(self, on: bool) -> None:
        self.body.setVisible(on)
        self._update_head()

    def set_modified(self, on: bool) -> None:
        self.modified = on
        self._update_head()

    def _update_head(self) -> None:
        arrow = "▾" if self.body.isVisible() else "▸"
        self.head.setText(f"{arrow} {self.title}{'  ●' if self.modified else ''}")


class ParamEditor(QWidget):
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
        self.widgets, self.sections = {}, {}
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
        combo.currentTextChanged.connect(
            lambda text: self._set("obj", ("object_profile",), "" if text == NONE_PROFILE else text))
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
            w.toggled.connect(lambda on: self._set(root, path, bool(on)))
        elif kind == "int":
            w = QSpinBox()
            w.setRange(-10 ** 9, 10 ** 9)
            w.setValue(int(value))
            w.setKeyboardTracking(False)
            w.valueChanged.connect(lambda v: self._set(root, path, int(v)))
        elif kind == "choice":
            w = QComboBox()
            w.addItems(choices)
            w.setCurrentText(str(value))
            w.currentTextChanged.connect(lambda text: self._set(root, path, text))
        else:
            w = QLineEdit("" if value is None else str(value))
            if kind == "float":
                w.setValidator(QDoubleValidator())
                w.editingFinished.connect(lambda: self._set_text(w, root, path, float))
            elif kind == "percent":
                w.setValidator(QRegularExpressionValidator(QRegularExpression(r"^-?\d+(\.\d+)?%$")))
                w.editingFinished.connect(lambda: self._set_text(w, root, path, str))
            elif kind == "null":
                w.setPlaceholderText("null")
                w.editingFinished.connect(lambda: self._set_text(w, root, path, _parse_null))
            else:
                w.editingFinished.connect(lambda: self._set_text(w, root, path, str))
        w.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        if comment:
            w.setToolTip(comment.lstrip("# "))
        self.widgets[(root,) + path] = w
        self._row(parent, path[-1], w)

    def _set_text(self, w: QLineEdit, root: str, path: tuple, parse) -> None:
        if not w.hasAcceptableInput() and w.validator() is not None:
            w.setText(str(self._get(root, path)))  # reject invalid text
            return
        try:
            self._set(root, path, parse(w.text()))
        except ValueError:
            w.setText(str(self._get(root, path)))

    # --- values ---
    def _get(self, root: str, path: tuple):
        node = self.obj if root == "obj" else self.params
        for key in path:
            node = node[key]
        return node

    def _set(self, root: str, path: tuple, value) -> None:
        node = self.obj if root == "obj" else self.params
        for key in path[:-1]:
            node = node.setdefault(key, {})
        if node.get(path[-1]) == value and type(node.get(path[-1])) is type(value):
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


def _parse_null(text: str):
    """Empty -> None; otherwise the YAML value of the text (so `0.5` becomes a float)."""
    return None if not text.strip() else yaml.safe_load(text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m tests.test_panel`
Expected: `ok`. If the `targetlen` path does not exist, print `load_params(object_profile="")["refine"]["pymeshlab"]["params"]` and use an existing percent key; do not change the editor.

- [ ] **Step 5: Commit**

```bash
git add functions/gui/panel.py tests/test_panel.py
git commit -m "feat(gui): yml-driven parameter editor with modified markers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Main window and entry point

**Files:**
- Create: `functions/gui/window.py`, `functions/gui/app.py`
- Modify: `scripts/run_pipeline.sh`

**Interfaces:**
- Consumes: everything above. `SystemConfigs`, `run_stage` (Task 5); `UiBridge` (Task 4); `PipelineRunner`, `STAGE_ORDER`, `STAGE_LABELS`, `first_blocked`, `initial_statuses`, `read_states`, `stale_after`, `stages_from` (Task 5); `Viewport` (Task 9); `CheckpointScene` (Task 10); `Timeline`, `InteractionHost`, `ParamEditor`, `LogView` (Tasks 11–12); `load_comments`, `list_object_profiles`, `save_object_profile` (Task 2); `load_object`, `load_params` (Task 1).
- Produces: `MainWindow(minimal=False)`, `main(argv=None) -> int`.

- [ ] **Step 1: Implement `functions/gui/window.py`**

```python
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
from functions.gui.params_io import list_object_profiles, load_comments, save_object_profile
from functions.gui.runner import (STAGE_LABELS, STAGE_ORDER, PipelineRunner, first_blocked, initial_statuses,
                                  read_states, stale_after, stages_from)
from functions.gui.scenes import CheckpointScene
from functions.gui.viewport import Viewport
from functions.pipeline.interface import SystemConfigs, run_stage
from functions.utils.config import load_object, load_params

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
        self.signals.event.connect(self._on_event)
        self.signals.log.connect(lambda text: self.log.append(text))
        self.bridge = UiBridge(self.signals.event.emit, minimal=minimal)
        self.runner = PipelineRunner(self.bridge, self.make_cfgs, run_stage)
        self.scene = None
        self.current_stage = None
        self.statuses = {}
        self._streams = (sys.stdout, sys.stderr)
        self._run_t0 = None
        self._build_ui()
        self._load(load_object())
        self.apply_theme(th.current())
        self.minimal_box.setChecked(minimal)
        self._set_minimal(minimal)
        self._clock = QTimer(self, interval=1000, timeout=self._tick)
        self._clock.start()
        self._flush = QTimer(self, interval=250, timeout=self._flush_timeline)

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

        self.timeline.rerun.connect(lambda s: self._start([s]))
        self.timeline.run_from.connect(lambda s: self._start(stages_from(s, self._params["pipeline"]["stages"])))
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
        """Hand the worker an immutable copy; it is read once per stage start (atomic reference swap)."""
        self._obj, self._params = self.editor.values()

    def make_cfgs(self) -> SystemConfigs:
        return SystemConfigs(obj=copy.deepcopy(self._obj), params=copy.deepcopy(self._params))

    def _reload_object(self, obj: dict) -> None:
        stem = obj.get("object_profile") or ""
        if stem:
            obj = load_object(stem)  # a snapshot restores its own object block
        pipeline = copy.deepcopy(self._params["pipeline"])
        params = load_params(profile=obj.get("profile"), object_profile=stem)
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
        print(f"[info]: saved object profile cfgs/profiles/objects/{stem}.yml")

    # --- run control ---
    def run_all(self) -> None:
        self._start([s for s in STAGE_ORDER if self._params["pipeline"]["stages"].get(s)])

    def _start(self, stages: list[str]) -> None:
        if self.runner.busy or not stages:
            return
        blocked = first_blocked(stages, read_states(self.states_path), self._params["pipeline"]["restore_align"])
        if blocked:
            stage, missing = blocked
            QMessageBox.warning(self, "Cannot run",
                                f"{STAGE_LABELS[stage]} needs results that are not in states.json yet: "
                                f"{', '.join(missing)}. Run the earlier stages first.")
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
            print(traceback.format_exc())
            self.scene = None
            self.viewport.unmount()
            self.bridge.resolve(None)

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
```

- [ ] **Step 2: Implement `functions/gui/app.py`**

```python
"""GUI entry point: `python -m functions.gui.app [--minimal]` (scripts/run_pipeline.sh calls this)."""
import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_pipeline", description="RORA pipeline GUI")
    parser.add_argument("--minimal", action="store_true",
                        help="no debug checkpoints, no live viewport during compute, terminal-only log")
    args = parser.parse_args(argv)
    try:
        from PySide6.QtWidgets import QApplication

        from functions.gui.window import MainWindow
    except ImportError as e:
        print(f"[error]: the GUI needs PySide6 and VTK's Qt support ({e}). Run: uv pip install -r requirements.txt")
        return 1
    app = QApplication(sys.argv[:1])
    app.setApplicationName("RORA")
    window = MainWindow(minimal=args.minimal)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Point the launcher at the GUI**

Replace the last line of `scripts/run_pipeline.sh` with:

```bash
cd "$(dirname "$0")/.." && exec python -m functions.gui.app "$@"
```

and its comment line with `# Launch the pipeline GUI. Settings: cfgs/object_cfg.yml, cfgs/parameters_cfg.yml. Pass --minimal for timing runs.`

- [ ] **Step 4: Smoke-run the window**

Run: `.venv/bin/python -c "import sys; from PySide6.QtCore import QTimer; from PySide6.QtWidgets import QApplication; app = QApplication([]); from functions.gui.window import MainWindow; w = MainWindow(); w.show(); QTimer.singleShot(1500, w.close); app.exec(); print('ok')"`
Expected: the window shows for 1.5 s (header, empty viewport with the view cube, timeline with cached/pending stages, parameters, log), then `ok`. Stage functions still use the old pop-ups until Tasks 14–15, so do not press Run yet.

- [ ] **Step 5: Run every logic test**

Run: `for t in test_config test_params_io test_bridge test_runner test_manip test_models test_view_math test_panel; do .venv/bin/python -m tests.$t || break; done`
Expected: `ok` eight times.

- [ ] **Step 6: Commit**

```bash
git add functions/gui/window.py functions/gui/app.py scripts/run_pipeline.sh
git commit -m "feat(gui): main window wiring runner, panel and viewport

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Stage integration — align, refine, decompose, bind, debug checkpoints

**Files:**
- Modify: `functions/pipeline/transform.py`, `functions/pipeline/refine.py`, `functions/pipeline/decompose.py`, `functions/pipeline/bind.py`, `functions/visualize/plots.py`

**Interfaces:**
- Consumes: `ui()` (Task 4), `AlignScene` (Task 10), `theme` (Task 3).
- Produces: `plots.show_links(links, title=...)` (used in Task 15). Every `show_*` in `plots.py` returns immediately unless `ui().debug`.

- [ ] **Step 1: Align — replace the pop-up with `AlignScene`**

In `functions/pipeline/transform.py`:
- Imports: remove `import vedo`, `from functools import partial`, `from functions.visualize.style import timed_show`; add `from functions.gui.bridge import ui`.
- Delete the whole `# --- vedo assembly helper ---` section (`_shift_assembly`) and the `# --- key callback ---` section (`key_press_callback`).
- Replace `stage_transform` with:

```python
def stage_transform(cfgs):
    tf_cfgs = cfgs.params["transform"]
    ui().plan([("load", "Load", True), ("auto", "Auto-align", bool(tf_cfgs["use_auto_alignment"])),
               ("manual", "Manual adjust", True), ("save", "Save", True)])

    ui().step("load")
    ms = pymeshlab.MeshSet()
    try:
        ms.load_new_mesh(cfgs.mesh_in_dir)
        ms.load_new_mesh(cfgs.gaussian_in_dir)
        ms.set_current_mesh(0)
    except pymeshlab.PyMeshLabException:
        print(f"[error]: Failed to find mesh. dir={cfgs.in_dir}")
        raise FileNotFoundError()
    mesh = ms.mesh(0)

    if tf_cfgs["use_auto_alignment"]:
        ui().step("auto")
        initial_transform = align_transform(ms)  # 4x4
        if initial_transform is None:
            print("[Warning] Auto-alignment failed. Using Identity.")
            initial_transform = np.eye(4)
    else:
        print("[Info] Auto-alignment disabled. Using Identity.")
        initial_transform = np.eye(4)

    # Manual adjustment in the viewport; rotations pivot on the world origin (ground plane stays put)
    ui().step("manual")
    verts, faces = mesh.vertex_matrix(), mesh.face_matrix()
    R0 = initial_transform[:3, :3].astype(np.float64)
    t0 = initial_transform[:3, 3].astype(np.float64)
    verts_vis = apply_Rt_points(verts.astype(np.float64), R0, t0)
    point_colors = cell_colors = None
    if mesh.has_vertex_color():
        point_colors = (mesh.vertex_color_matrix()[:, :3] * 255).astype(np.uint8)
    elif mesh.has_face_color():
        cell_colors = (mesh.face_color_matrix()[:, :3] * 255).astype(np.uint8)
    from functions.gui.scenes import AlignScene  # GUI-only import keeps this module importable headless
    fine_M = ui().interact(AlignScene(verts_vis, faces, point_colors, cell_colors))

    # accumulate transforms: project each to pure rotation before composing
    ui().step("save")
    fine_M = _closest_rotation(np.asarray(fine_M, dtype=float))
    initial_transform = _closest_rotation(initial_transform)
    total_T = fine_M @ initial_transform

    os.makedirs(cfgs.mesh_working_dir, exist_ok=True)
    mesh_out = os.path.join(cfgs.mesh_working_dir, f"transformed_mesh.{cfgs.extension}")
    save_mesh_with_transform(mesh, mesh_out, total_T)

    # save gaussian (positions + normals + quats, preserve other PLY elements)
    ply = PlyData.read(cfgs.gaussian_in_dir)
    gaussian_out = os.path.join(cfgs.mesh_working_dir, f"transformed_gaussian.{cfgs.extension}")
    save_gaussian_with_transform(ply, gaussian_out, total_T)

    states = JsonHandler(cfgs.json_states_dir, auto_save=True)
    states.transform = {}
    states.transform.matrix = total_T.tolist()
    states.transform.dirs = {"mesh": mesh_out, "gaussian": gaussian_out}
    ms.clear()
```

- In `restore_transform`, add `ui().plan([("load", "Load", True), ("restore", "Restore", True), ("save", "Save", True)])` and `ui().step("load")` as the first lines of the body, `ui().step("restore")` right before the `# 4) Apply & save mesh` comment, and `ui().step("save")` right before the `# 6) Persist outputs` comment.

Run: `grep -n "vedo\|timed_show\|partial\|key_press_callback\|_shift_assembly" functions/pipeline/transform.py`
Expected: no output.

- [ ] **Step 2: Refine — sub-steps, checkpoints, streamed point2mesh**

In `functions/pipeline/refine.py`, add `from functions.gui.bridge import ui`. Add above `run_pymeshlab_refinement`:

```python
PYMESHLAB_STEPS = [("cleaning", "① Cleaning"), ("reconstruction", "② Poisson"),
                   ("vertex_selection", "③ Artifact removal"), ("decimation", "④ Simplification"),
                   ("remeshing", "⑤ Remeshing"), ("occlusion_repair", "⑥ Occlusion repair"),
                   ("close_holes", "⑦ Hole closing"), ("attribute_transfer", "⑧ Attribute restoration")]
```

In `run_pymeshlab_refinement`, right after `refCfgs = ...`, add:

```python
    enabled = {k: bool(refCfgs["steps"].get(k, True)) for k, _ in PYMESHLAB_STEPS}
    ui().plan([("load", "Load", True)] + [(k, label, enabled[k]) for k, label in PYMESHLAB_STEPS]
              + [("save", "Save", True)])
    ui().step("load")
```

Then add `ui().step("<key>")` as the first line inside each `if refCfgs["steps"].get("<key>", True):` block, for all eight keys, and `ui().step("save")` right before `mesh_out_dir = os.path.join(cfgs.mesh_working_dir, f"refined_mesh...`. Leave the `if debug_mode: show_meshset(...)` lines as they are.

In `run_point2mesh_refinement`, add as the first lines:

```python
    ui().plan([("p2m_prepare", "Prepare", True), ("point2mesh", "point2mesh", True), ("p2m_save", "Save", True)])
    ui().step("p2m_prepare")
```

Replace the block from `print(f"[point2mesh]: Running command: ...")` through the `if result.returncode != 0:` branch with:

```python
    print(f"[point2mesh]: Running command: {' '.join(cmd)}")
    ui().step("point2mesh")
    import subprocess
    proc = subprocess.Popen(cmd, cwd=p2m_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1)
    for line in proc.stdout:  # stream to the terminal / log panel while it runs
        print(f"[point2mesh] {line.rstrip()}")
    if proc.wait() != 0:
        print(f"[point2mesh warning]: point2mesh exited with code {proc.returncode} (output above).")
        print("[point2mesh warning]: Falling back to PyMeshLab refinement.")
        run_pymeshlab_refinement(cfgs, debug_mode=debug_mode)
        return

    ui().step("p2m_save")
```

- [ ] **Step 3: Decompose and bind — sub-steps**

In `functions/pipeline/decompose.py`, add `from functions.gui.bridge import ui`; at the top of `stage_decompose` add:

```python
    ui().plan([("load", "Load", True), ("coacd", "CoACD", True), ("save", "Save fragments", True)])
    ui().step("load")
```

then `ui().step("coacd")` right before `# Run convex decomposition` and `ui().step("save")` right before `# Save intermediate state into the json file`.

In `functions/pipeline/bind.py`, add `from functions.gui.bridge import ui`; right after the docstring of `stage_bind` add:

```python
    ui().plan([("load", "Load", True), ("zcut", "Z-cut", True), ("knn", "KNN assignment", True),
               ("save", "Save", True)])
    ui().step("load")
```

then `ui().step("zcut")` before `# --- Z cut by relative threshold to mesh diagonal ---`, `ui().step("knn")` before `# --- KNN assignment on z-kept points ---`, and `ui().step("save")` before `# Save per-part except -1`.

- [ ] **Step 4: Debug viewers become checkpoints (`functions/visualize/plots.py`)**

Rewrite the module so every viewer returns early unless `ui().debug`, prepares numpy data on the worker, and builds vedo actors in a closure that runs on the GUI thread. Replace the docstring, imports, `_show`, and `show_meshset` with:

```python
"""Debug checkpoints. Each viewer prepares data on the worker thread and passes a closure that builds the
vedo actors on the GUI thread; the main viewport shows it until Continue (debug_mode on, not --minimal)."""
import numpy as np
import pymeshlab
import vedo

from functions.gui import theme
from functions.gui.bridge import ui
from functions.math.geometry import normalize
from functions.math.connection import merge_lines, plane_intersections, unicon_normal
from functions.visualize.style import BG_RGB, PASTEL, arrow_params, label_colors, pastel, pastel_hex


def _show(title: str, build) -> None:
    """Block on a debug checkpoint; `build()` returns the actors and runs on the GUI thread."""
    ui().checkpoint(title, build)


def show_meshset(ms: pymeshlab.MeshSet, title: str):
    """Current mesh of a MeshSet, with vertex colors if present."""
    if not ui().debug:
        return
    if not isinstance(ms, pymeshlab.MeshSet) or ms.mesh_number() == 0:
        print(f"[Debug Viewer] Skipping: Invalid MeshSet for '{title}'")
        return
    m = ms.current_mesh()
    verts, faces = m.vertex_matrix(), m.face_matrix()
    if verts.size == 0 or faces.size == 0:
        print(f"[Debug Viewer] Skipping '{title}': No geometry to show.")
        return
    colors = None
    if m.has_vertex_color():
        c = m.vertex_color_matrix()[:, :3]
        colors = (c * 255).astype("uint8") if c.max() <= 1.0 else c.astype("uint8")
    print(f"[Debug Viewer] Showing: {title}")

    def build():
        actor = vedo.Mesh([verts, faces]).c(theme.current().mesh)
        if colors is not None:
            actor.pointcolors = colors
        return [actor]

    _show(title, build)
```

Keep `_arrow` unchanged. Convert the other viewers the same way; the actor-building code moves into `build()` unchanged except where noted:

```python
def show_labels(verts, faces, vert_label, title: str = "Segmented Parts Preview"):
    """Mesh colored by part label (transparent to show the inside)."""
    if not ui().debug:
        return
    rgb = label_colors(vert_label)

    def build():
        mesh = vedo.Mesh([verts, faces])
        mesh.pointcolors = rgb
        return [mesh.alpha(0.4)]

    _show(title, build)


def show_links(links, title: str = "Loaded link meshes"):
    """Per-link meshes produced by the articulate stage."""
    if not ui().debug:
        return
    data = [(np.asarray(m.vertices), np.asarray(m.faces)) for _, m in sorted(links.items())]
    _show(title, lambda: [vedo.Mesh([v, f]).c(theme.current().mesh).alpha(0.5) for v, f in data])
```

- `show_cycles(...)`: add `if not ui().debug: return` first; keep the cycle loop with its `print` lines on the worker, but collect `(points, color)` pairs instead of creating `vedo.Spheres`; build in the closure:

```python
    spheres = []  # filled in the loop: spheres.append((verts[np.asarray(cycle, dtype=int)], pastel_hex(target)))

    def build():
        if vert_label is None:
            actors = [vedo.Mesh([verts, faces]).c(part_color).alpha(0.35)]
        else:
            is_part = vert_label[faces[:, 0]] == idx_part
            actors = [vedo.Mesh([verts, f]).c(c).alpha(a) for f, c, a in
                      ((faces[~is_part], "lightgray", 0.15), (faces[is_part], part_color, 0.35)) if len(f)]
        return actors + [vedo.Spheres(p, r=sphere_r, c=c, res=8) for p, c in spheres]

    _show(title, build)
```

- `show_axis_estimation(...)`: add `if not ui().debug: return`; keep the `print` lines on the worker; move every `actors.append(...)` / `vedo.*` construction into `def build():` (same code, same order) and call `_show(title, build)`.
- `show_bicons(...)`: add `if not ui().debug: return`; keep the per-bicon loop, the `print` lines, and the vector math on the worker. Replace each of the three `vedo.Plotter(title=..., axes=0, size=(1800, 1800)).show([...], interactive=True).close()` calls with `_show(<same title string>, lambda: [<same actor list>])`, building `mesh` inside a local `make_mesh()` helper that the lambdas call (so the colored mesh is created on the GUI thread):

```python
        def make_mesh(rgb=rgb):
            mesh = vedo.Mesh([verts, faces])
            mesh.pointcolors = rgb
            return mesh.alpha(0.4).pickable(False)
```

  The checkpoint blocks until Continue, and `build` runs before the loop moves on, so plain closures over the loop variables are safe.

Run: `grep -n "Plotter\|\.show(" functions/visualize/plots.py`
Expected: no output.

- [ ] **Step 5: Verify headless imports and tests**

Run: `.venv/bin/python -c "import functions.pipeline.interface as i; print(sorted(i.STAGE_FUNCS))" && .venv/bin/python -m tests.test_runner`
Expected: the six stage names, then `ok`.

- [ ] **Step 6: Manual check in the GUI (align + refine + decompose)**

Set `pipeline.debug_mode: true` in `cfgs/parameters_cfg.yml` locally (do not commit it), run `bash scripts/run_pipeline.sh`, untick Segment/Articulate/Bind in the timeline, press Run, and check:
1. Align: the timeline expands Load → Auto-align → Manual adjust (⏸ input); the mesh shows in the viewport with axes and grid; keys and gizmo move it; Done continues.
2. Refine: each enabled pymeshlab step lights up in turn; each debug checkpoint appears in the same viewport with Continue; disabled steps are struck through; when the stage ends the sub-steps collapse to `n/m · Xs`.
3. Decompose: CoACD runs with the running dot; afterwards `working/<object>/attributes/timing.json` exists.

Restore `debug_mode` to its committed value.

- [ ] **Step 7: Commit**

```bash
git add functions/pipeline/transform.py functions/pipeline/refine.py functions/pipeline/decompose.py functions/pipeline/bind.py functions/visualize/plots.py
git commit -m "feat(pipeline): report sub-steps and debug checkpoints through the GUI bridge

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Stage integration — segment, articulate; delete the old UI

**Files:**
- Modify: `functions/pipeline/segment.py`, `functions/pipeline/articulate.py`, `functions/visualize/style.py`, `functions/__init__.py`, `README.md`
- Delete: `functions/visualize/select.py`

**Interfaces:**
- Consumes: `ui()` (Task 4), `PartSelectScene`, `JointSelectScene` (Task 10), `group_fragments` (Task 6), `plots.show_links` (Task 14).

- [ ] **Step 1: Segment**

In `functions/pipeline/segment.py`: replace `from functions.visualize.select import select_parts` with `from functions.gui.bridge import ui` and `from functions.gui.models import group_fragments`. In `stage_segment`:
- After the opening `print("[info] Starting stage_segment...")`, add:

```python
    ui().plan([("load", "Load", True), ("select", "Part selection", True), ("label", "Vertex labeling", True),
               ("save", "Save", True)])
    ui().step("load")
```

- Replace the whole `# selection UI` block (the `if cfgs.debug_mode:` controls `print`s through `print("[info] Part selection finished.")`) with:

```python
    # part selection in the viewport
    ui().step("select")
    from functions.gui.scenes import PartSelectScene  # GUI-only import keeps this module importable headless
    owner = ui().interact(PartSelectScene([(f.vertices, f.faces) for f in fragments], verts, faces, parts_num))
    parts = group_fragments(fragments, owner, parts_num)
    print("[info] Part selection finished.")
```

- Add `ui().step("label")` before `# vertex labels` and `ui().step("save")` before the `# persist:` comment.

- [ ] **Step 2: Articulate**

In `functions/pipeline/articulate.py`: replace `from functions.visualize.select import select_joint_vectors` with `from functions.gui.bridge import ui`; change `from functions.visualize.plots import show_bicons` to `from functions.visualize.plots import show_bicons, show_links`. In `stage_articulate`:
- After the `print("[info] Starting stage_articulate...")` line, add:

```python
    ui().plan([("load", "Load", True), ("unicons", "Unicons", True), ("fusion", "Fusion", True),
               ("vectors", "Vector selection", True), ("links", "Link meshes", True), ("urdf", "URDF", True)])
    ui().step("load")
```

- Add `ui().step("unicons")` before `print("[info] Estimating unidirectional connections (unicons)...")`, `ui().step("fusion")` before `print("[info] Fusing unicons ...")`, `ui().step("links")` before `# per-link meshes + patch fill`, and `ui().step("urdf")` before `# Generate URDF File`.
- Replace the `# vector selection UI (part-pair-wise)` block (controls `print`s through `print("[info] Vector selection finished.")`) with:

```python
    # vector selection in the viewport (all part pairs in one scene)
    ui().step("vectors")
    print("[info] Starting interactive vector selection...")
    if bicons:
        from functions.gui.scenes import JointSelectScene  # GUI-only import
        ui().interact(JointSelectScene(bicons, verts, faces, vert_label))
    print("[info] Vector selection finished.")
```

- Replace the final debug viewer block (`if cfgs.debug_mode: actors = [...]; vedo.show(...)`) with `show_links(links)`.
- Run `grep -n "vedo" functions/pipeline/articulate.py`; if only the `import vedo` line remains, delete it.

- [ ] **Step 3: Delete the old UI code**

```bash
git rm functions/visualize/select.py
```

In `functions/visualize/style.py`, delete `timed_show` and the now-unused `import time`. In `functions/__init__.py`, delete `total_gui_time = 0.0`.

Run: `grep -rn "select_parts\|select_joint_vectors\|timed_show\|total_gui_time\|visualize.select" functions scripts`
Expected: no output.

- [ ] **Step 4: Update the README run section**

In `README.md`, replace the `pipeline.debug_mode` table row with:

```markdown
| `pipeline.debug_mode` | Pause at intermediate results in the viewport (ignored with `--minimal`). |
```

Replace the text from `Some stages open interactive GUI windows.` through the **articulate** bullet with:

```markdown
The pipeline runs in one window: a 3D viewport on the left, and on the right the stage timeline,
the current interaction, the parameters, and the log. Press **▶ Run** to run the enabled stages.
Hover a stage to **↻ re-run** it or **▶ run from** it; edit parameters first to re-run with new values.
**Save object profile** writes every stage setting for this object to
`cfgs/profiles/objects/<object>_<date>_<time>.yml` (shared yml files are never changed).

- **align**: seat the object on z = 0 with Front along +X. Rotate X/Y/Z: `N/B`, `J/H`, `I/U`.
  Move X/Y/Z: `W/S`, `D/A`, `Space/Z`. Or drag the gizmo, or type values in the panel. `Enter`: done.
- **segment (parts)**: pick a part chip (or `Tab`), left click assigns a fragment, right click reverts.
- **articulate (joint axis)**: click an arrow to cycle None → Revolute (amber) → Prismatic (blue);
  `Enter` / **Next pair** moves through the part pairs.
- Everywhere: the view cube (top right) snaps the camera to a face, edge, or corner; `R` resets the view,
  `G` toggles the gizmo.

`bash scripts/run_pipeline.sh --minimal` skips debug pauses and live rendering for timing runs.
```

Replace `Per-stage timings are printed at the end.` with:

```markdown
Per-stage timings (compute time excludes time spent waiting for input) are printed at the end and saved
to `working/<object_name>/attributes/timing.json`.
```

In the "Example: rerun some stages" section, add before the yaml block: `In the GUI, untick stages in the timeline or use ↻ / ▶ on a stage. Without the GUI checkboxes, set:`.

- [ ] **Step 5: Verify**

Run: `for t in test_config test_params_io test_bridge test_runner test_manip test_models test_view_math test_panel; do .venv/bin/python -m tests.$t || break; done && .venv/bin/python -c "import functions; import functions.pipeline.interface"`
Expected: `ok` eight times, and the import succeeds.

- [ ] **Step 6: Commit**

```bash
git add -A functions README.md
git commit -m "feat(pipeline): segment and articulate in the unified viewport; remove pop-up UI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: End-to-end verification

**Files:** none (fix-ups only if a check fails, each in its owning file with its own commit).

- [ ] **Step 1: Baseline for comparison**

Before running the new GUI on `apr_diffuser`, copy the last pre-change outputs if they exist: `cp -r working/apr_diffuser working/apr_diffuser_before 2>/dev/null || true` (`working/` is git-ignored).

- [ ] **Step 2: Full run with debug on**

Set `pipeline.debug_mode: true` locally and run `bash scripts/run_pipeline.sh`. Run every stage and check:
1. One window the whole time; no other window opens.
2. Every debug checkpoint shows in the viewport with Continue; the timeline expands the active stage and collapses finished ones to `n/m · Xs`.
3. Align, segment, and articulate interactions work as in the README; the final `states.json` has `transform`, `refine`, `decompose`, `segment`, `articulate`; `export/apr_diffuser/urdf/object.urdf` and `gaussian/gaussian_*.ply` exist.
4. Using the same inputs and the same picks as the baseline run, `states.json["transform"]["matrix"]` matches the baseline when no manual adjustment is made (Enter immediately in Align).

- [ ] **Step 3: Re-run with a changed parameter**

Change `decompose.coacd.threshold` in the panel (the Decompose section shows ●), hover Decompose and press ↻. Check: Segment, Articulate, Bind turn amber (stale); afterwards ▶ on Segment runs Segment → Bind.

- [ ] **Step 4: Save an object profile**

Press **Save object profile**. Check: a new `cfgs/profiles/objects/apr_diffuser_<date>_<time>.yml` with an `object` block and every stage section but no `pipeline`; `cfgs/object_cfg.yml` points at it with its comments intact; `git diff cfgs/parameters_cfg.yml cfgs/profiles/*_params_cfg.yml` is empty; the profile appears selected in the Object section.

- [ ] **Step 5: Minimal mode, stop, theme, close**

1. `bash scripts/run_pipeline.sh --minimal`: no checkpoints, the log stays in the terminal, interactions still work, `timing.json` has `"minimal": true`.
2. Press ■ Stop during Part selection: Segment shows `stopped`; then ▶ on Segment runs again.
3. Toggle ◐ mid-run: panel, viewport background, view cube, gizmo, and joint arrows switch theme.
4. Close the window during a run: a confirmation appears; Yes quits without a hang.

- [ ] **Step 6: Final review gate**

Restore `debug_mode`, run the eight test modules once more, and request a whole-branch review (superpowers:requesting-code-review) before merging.

