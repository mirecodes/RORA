# Unified Pipeline GUI — Design

Date: 2026-10-20
Status: draft, awaiting review

## 1. Goal

Replace the per-stage vedo pop-up windows (Align, Segment, Articulate, and all debug viewers) with a
single local desktop window: a 3D viewport plus a side panel that shows pipeline progress, the current
interaction, editable parameters, and the log.

Success criteria:

- One window for the whole run. No window opens or closes between stages.
- Consistent size, typography, and colors (light and dark themes from one token set).
- Every stage can be re-run with edited parameters without restarting the app.
- Pure compute time per stage and per step is measured without GUI or user-wait time.
- A `--minimal` mode keeps GUI overhead close to zero during compute.
- Input handling is structured so per-arrow mouse manipulation can be added later without rework.

Out of scope: remote/web use, multi-user use, headless replay benchmarking (the interface allows it
later; see §9), and live preview of parameter changes.

## 2. Decisions

| Topic | Decision |
|---|---|
| Stack | PySide6 + vedo embedded through `QVTKRenderWindowInteractor` (`vedo.Plotter(qt_widget=...)`). |
| Execution model | Pipeline runs on a worker thread. Stage code blocks on `ui().interact(...)`. All VTK rendering happens on the main thread. |
| Layout | Two columns: viewport on the left, one vertical side panel on the right (no tabs). |
| Window | 16:9, default 1600×900. Side panel is 22% of the width, clamped to 300–380 px, with a draggable splitter. |
| Progress | Git-log style timeline. Only the active stage expands into sub-steps. Finished stages collapse to one summary line (`4/4 · 12s`). |
| Debug viewers | Become checkpoints in the same viewport. They pause until **Continue** is pressed. |
| Parameter editing | Re-run a single stage or run from any stage, with edited parameters. Edits go to an in-memory copy. **Save** writes a new object-specific profile (`<object>_<date>_<time>.yml`). Shared files are never modified. |
| Input | Keyboard shortcuts (existing bindings), panel buttons/fields, and a 3D transform gizmo. All three produce the same 4×4 delta. |
| Navigation | View cube in the viewport corner. Clicking a face, edge, or corner snaps the camera. |
| Theme | Light and dark token sets with a toggle. |
| Language | All UI text, code, comments, and docs in English (see `CLAUDE.md`). |
| New dependencies | `PySide6`, `ruamel.yaml` (round-trip yml saving that keeps comments). |
| Entry point | `scripts/run_pipeline.sh` launches the GUI. `--minimal` is passed through. |

## 3. Layout

```
┌──────────────────────────────────────────────────────────────┬──────────────────┐
│ RORA · apr_diffuser · profile: real_object    ▶ Run  ■ Stop   00:42  ◐ theme   │
├──────────────────────────────────────────────────────────────┬──────────────────┤
│ ┌─ overlay: stage · scene title ─────┐              [cube]   │ PIPELINE         │
│ │ one-line hint                      │                       │ ● Align  4/4 12s │
│ └────────────────────────────────────┘                       │ ◉ Refine   3/8   │
│                                                              │ │ ● ① Cleaning   │
│                     3D viewport                              │ │ ◉ ③ Artifact…  │
│                                                              │ │ ○ ④ …          │
│                                                              │ ○ Decompose      │
│ ┌─ overlay: key hints ───────────────┐                       │ INTERACTION      │
│ │ Tab next part · R reset view       │                       │ PARAMETERS       │
│ └────────────────────────────────────┘                       │ LOG ▸ (last line)│
└──────────────────────────────────────────────────────────────┴──────────────────┘
```

Side panel sections, top to bottom:

1. **Pipeline**: the timeline (§5).
2. **Interaction**: the widget supplied by the active scene (part chips, joint-pair navigation,
   transform fields, Continue/Done). It shows "Idle" or "Computing…" when no scene is active.
3. **Parameters**: the parameters of the selected stage (§7).
4. **Log**: collapsed to the last line by default. Clicking it expands the log.

Viewport overlays: the scene title and a one-line hint at the top left, key hints at the bottom left
(generated from `Scene.controls`), and the view cube at the top right.

## 4. Architecture

```
functions/gui/
  app.py        # main(): parse --minimal, QApplication, MainWindow, PipelineRunner
  window.py     # MainWindow: header bar, QSplitter(viewport | side panel), theme toggle
  viewport.py   # Viewport: QVTKRenderWindowInteractor + one vedo.Plotter; mount/unmount scenes;
                #   overlays; render suspend/resume (minimal mode)
  viewcube.py   # ViewCube: corner navigation cube (§6.4)
  panel.py      # Timeline, InteractionHost, ParamEditor, LogView widgets
  bridge.py     # UiBridge + ui() accessor + StageTimer
  runner.py     # PipelineRunner: worker thread; run-all / re-run / run-from / stop
  scenes.py     # Scene base, CheckpointScene, AlignScene, PartSelectScene, JointSelectScene
  manip.py      # Transformable protocol, AssemblyTarget, VectorGroupTarget, key/panel delta inputs
  gizmo.py      # TransformGizmo (§6.3)
  params_io.py  # ruamel round-trip load/save, field-type inference, save routing (§7)
  theme.py      # LIGHT / DARK tokens → Qt stylesheet + VTK colors
```

### 4.1 Threading and the bridge

- `PipelineRunner` runs stage functions on a `threading.Thread`.
- Stage code reaches the GUI only through `ui()`, a module-level accessor in `bridge.py` that returns
  the active `UiBridge`. There is no signature churn: deep callers such as
  `math/axis_estimation.py → plots.show_cycles` work unchanged once `plots._show` is redirected.
- `UiBridge` methods, all called from the worker thread:

  | Method | Behavior |
  |---|---|
  | `stage(name, steps)` | Declares the stage's sub-steps (`[(key, label, enabled)]`). Disabled steps render as skipped. |
  | `step(key)` | Marks the previous step done and `key` running. Records timing. |
  | `checkpoint(title, payload)` | Shows a `CheckpointScene` and blocks until Continue. No-op when debug is off or in minimal mode. |
  | `interact(scene) -> result` | Mounts the scene and blocks until Done. Raises `PipelineStopped` on Stop. |
  | `check_stop()` | Raises `PipelineStopped` if Stop was requested. Called by `step()`. |

- Requests cross threads through Qt signals (queued connections). The worker waits on a
  `threading.Event` for the result.
- Worker → GUI payloads are plain data only (numpy arrays, dicts, lists). vedo/VTK objects are created
  in `Scene.mount()` on the main thread.
- Logging: `print` stays as it is. In full mode, `sys.stdout`/`sys.stderr` are teed to the terminal
  and to `LogView` through a signal. In minimal mode, output goes to the terminal only.

### 4.2 Changes to existing code

| File | Change |
|---|---|
| `pipeline/interface.py` | `execute_pipeline` is split into `run_stage(cfgs, name)` plus the stage table. The GUI builds a fresh `SystemConfigs(obj=..., params=...)` per stage from its in-memory copy, and the default `obj` comes from `load_object()` (object profile applied). The timing summary moves to `StageTimer`. `__main__` launches the GUI. |
| `pipeline/transform.py` | Uses `ui().interact(AlignScene(...))` and receives the fine 4×4. `key_press_callback`, `_shift_assembly`, and the printed controls are deleted. |
| `pipeline/refine.py` | Adds `ui().stage(...)` and `ui().step(...)`. `show_meshset` calls become `ui().checkpoint(...)`. point2mesh output is streamed to the log (`Popen` line reading) instead of being captured at the end. |
| `pipeline/decompose.py`, `bind.py` | Add `stage`/`step` calls. |
| `pipeline/segment.py` | Uses `ui().interact(PartSelectScene(...))`. Printed controls are deleted. |
| `pipeline/articulate.py` | Uses `ui().interact(JointSelectScene(...))`. Printed controls are deleted. |
| `visualize/plots.py` | `_show` and `show_meshset` build a payload and call `ui().checkpoint(...)`. |
| `visualize/select.py` | Deleted. Its logic moves to `PartSelectScene` and `JointSelectScene`. |
| `visualize/style.py` | Keeps the part palette and arrow geometry. Joint colors come from `theme.py`. `timed_show` is deleted. |
| `functions/__init__.py` | `total_gui_time` is removed (replaced by `StageTimer`). |
| `utils/config.py` | `load_params` applies the object profile layer (`object_cfg.yml: object_profile`). |
| `cfgs/object_cfg.yml` | Adds `object_profile: null`. |
| `cfgs/profiles/objects/` | New directory for GUI-saved object profiles (tracked in git). |
| `requirements.txt` | Adds pinned `PySide6` and `ruamel.yaml`. |
| `.gitignore` | Adds `.superpowers/`. |

### 4.3 Sub-steps per stage

| Stage | Sub-steps (**bold** = interactive) |
|---|---|
| Align | Load → Auto-align → **Manual adjust** → Save |
| Align (restore) | Load → Restore → Save |
| Refine (pymeshlab) | ① Cleaning → ② Poisson → ③ Artifact removal → ④ Simplification → ⑤ Remeshing → ⑥ Occlusion repair → ⑦ Hole closing → ⑧ Attribute restoration (each skipped when `steps.<x>: false`) |
| Refine (point2mesh) | Prepare → point2mesh (spinner, streamed log) → Save. On failure, the pymeshlab sub-steps are appended. |
| Decompose | Load → CoACD (spinner) → Save fragments |
| Segment | Load → **Part selection** → Vertex labeling → Save |
| Articulate | Load → Unicons → Fusion → **Vector selection** (pair i/N) → Link meshes → URDF |
| Bind | Load → Z-cut → KNN assignment → Save |

## 5. Timeline and run control

Stage row states: `pending` (hollow), `cached` (gray filled: present in `states.json` from an earlier
run), `running` (accent, expanded), `done` (green, collapsed summary), `stale` (amber hollow: an
upstream stage was re-run after this one finished), `failed` (red), `stopped` (gray, struck through).

Sub-step states: `pending` (dim dot), `running` (accent dot), `waiting` (accent dot + "⏸ checkpoint"
or "⏸ input"), `done` (green dot + duration), `skipped` (hollow dot, struck through).

Controls:

- **Header ▶ Run**: runs all stages enabled in `pipeline.stages`, in order.
- **Header ■ Stop**: cooperative. It takes effect at the next `step()` boundary, or immediately when
  the worker is blocked in `interact`/`checkpoint`. Native calls (CoACD, Poisson) cannot be
  interrupted mid-call.
- **Stage row click**: selects the stage, so Parameters shows its section and finished stages expand
  their sub-steps.
- **Stage row hover actions** (only when idle): `↻ Re-run` (this stage only) and `▶ Run from here`.
  Actions whose upstream data is missing from `states.json` are disabled, with a tooltip naming the
  missing stage.
- Re-running stage X marks finished downstream stages `stale`.
- Each stage row has a checkbox bound to `pipeline.stages.<name>`.

Status is kept in memory. On startup, stages with entries in `states.json` show as `cached`.

## 6. Interaction

### 6.1 Scenes

```python
class Scene:
    title: str
    hint: str
    controls: list[tuple[str, str]]           # (key, description) → overlay + panel
    def mount(self, plotter, host) -> None    # build actors + Interaction widget (main thread)
    def unmount(self) -> None
    def on_key(self, key: str) -> bool        # True if handled
    def on_pick(self, actor, button: str) -> None
    def result(self): ...
```

| Scene | Content | Result |
|---|---|---|
| `CheckpointScene` | View-only payload (meshes, point sets, arrows) styled from theme tokens. **Continue**. | `None` |
| `AlignScene` | Mesh (vertex colors if present), world axes, ground grid, gizmo. Panel: rotation X/Y/Z (deg), translation X/Y/Z, step sizes, Reset, Done. | Fine 4×4 (same convention as the current `assembly.transform.matrix`, then composed as `fine @ initial`). |
| `PartSelectScene` | Base mesh plus pickable fragments. Panel: part chips (View, Part 1..N) with fragment counts. Left click assigns, right click reverts, Tab cycles parts. Done. | Fragment → part owner list. Compaction of empty parts stays in `segment.py`. |
| `JointSelectScene` | All part pairs in one scene. Panel: pair list with Prev/Next and a per-pair count of revolute/prismatic vectors, plus a legend. Clicking an arrow cycles None → Revolute → Prismatic → None. Gizmo and keys move all vectors of the current pair. Done. | The `bicons` vectors updated (`state`, `order`, `center`, `n`), as `select_joint_vectors` does today. |

### 6.2 Transformable targets and inputs

```python
class Transformable(Protocol):
    def pivot(self) -> np.ndarray: ...            # gizmo position
    def apply(self, delta: np.ndarray) -> None: ...  # 4×4 world-space delta about pivot()
```

- `AssemblyTarget` (Align): accumulates the matrix applied to the mesh assembly. The pivot is the world
  origin, the same as today. The goal is to seat the object on z=0, so rotations must keep the ground
  plane and axes fixed instead of spinning the object about its own center. The gizmo sits at the
  origin.
- `VectorGroupTarget` (Articulate): applies the delta to every vector of the current pair the same way
  the old key handler did. The translation part shifts every `center`. The rotation part turns every
  `n`, and each arrow rotates in place about its own center. The gizmo sits at the mean center.
- Inputs: key bindings, panel buttons/fields, and the gizmo all build a delta and call
  `scene.apply(delta)`. That call forwards to `target.apply`, re-renders, and syncs the panel fields.
- Extension point: a later `SingleVectorTarget` plus Shift+click on an arrow and
  `gizmo.attach(target)` gives per-arrow mouse control. No other code changes are needed.

Key bindings, shared by Align and Articulate:

| Keys | Action |
|---|---|
| `W`/`S`, `D`/`A`, `Space`/`Z` | ±X, ±Y, ±Z translate (step = 2% of the scene diagonal by default) |
| `B`/`N`, `H`/`J`, `U`/`I` | ∓/± rotate about X, Y, Z (step = 1° for Align, 1.5° for Articulate by default) |
| `Tab` | Next part (Segment) |
| `R` | Reset view (isometric) |
| `G` | Toggle gizmo |
| `Enter` | Done / Continue |

The default VTK key bindings (wireframe, quit, and so on) are removed from the interactor.

### 6.3 Transform gizmo

- Three axis arrows: dragging one translates along that axis. Mouse motion is projected onto the
  axis's screen-space direction.
- Three rotation rings: dragging one rotates about that axis by the screen-space angle swept around
  the pivot.
- Constant on-screen size, rescaled on camera change. Hovered handles are highlighted. Axis colors come
  from the theme (X red, Y green, Z blue, slightly desaturated).
- While dragging, camera interaction is suspended. Gizmo handles take pick priority over scene
  actors.
- `vtkBoxWidget2` is not used: it has no axis constraints, mixes in scaling, and cannot attach to
  arbitrary targets.

### 6.4 View cube

- A 26-piece cube (6 faces, 12 edges, 8 corners) drawn in an overlay renderer in the top-right
  corner (~110 px). It follows the main camera's orientation.
- Axes follow the URDF convention: Z up, Front = +X. Side labels follow the viewer, as in CAD view
  cubes: looking at Front, +Y is on the right, so +X Front, −X Back, +Y Right, −Y Left, +Z Top,
  −Z Bottom.
- Click actions (camera direction = normalized sum of the normals of the faces the piece touches):
  - Face: looks straight at that face.
  - Edge: the two adjacent faces at 45°.
  - Corner: the three adjacent faces (isometric).
- The camera animates over about 200 ms and keeps its focal point and distance. The view-up vector is
  +Z, except for Top (view-up −X, Front at the bottom of the screen) and Bottom (view-up +X, Front at
  the top, as when the object is flipped over its front edge).
- Hovered pieces are highlighted. `R` resets to the Front-Right-Top corner view.

## 7. Parameters

- **Layering** (later layers override earlier ones):
  1. `cfgs/parameters_cfg.yml` (base, shared)
  2. `cfgs/profiles/<profile>_params_cfg.yml` (shared category profile, for example `real_object`)
  3. `cfgs/profiles/objects/<object_profile>.yml` (object-specific full snapshot, written by the GUI)

  `object_cfg.yml` gains an `object_profile:` key (file stem, `null` = none). `utils/config.load_params`
  applies layer 3 after layer 2. Because a snapshot contains every stage section, it fully determines
  the stage parameters; layers 1+2 still supply `pipeline` and any keys added to the base file after
  the snapshot was saved. The snapshot's `object` block overrides the matching `object_cfg.yml` values
  (`extension`, `profile`, `parts.num`). If the file is missing, the loader warns and skips the layer.
- **Sections**, mapped to stages: Pipeline (global, collapsed), Object (`object_name`, `extension`,
  `profile`, `object_profile`, `parts.num`), Align (`transform`), Refine, Decompose, Segment
  (+ `parts.num`), Articulate, Bind, Visualization (global). Selecting a stage shows its section
  first. Nested dicts become collapsible groups.
- **Object profile selector**: a combo box in the Object section lists `none` plus every
  `cfgs/profiles/objects/<object_name>_*.yml` for the current object, newest first. Changing it
  reloads the parameters (idle only).
- **Widget inference**:

  | Value | Widget |
  |---|---|
  | `bool` | Checkbox |
  | `int` | Spin box |
  | `float` | Double spin box |
  | `"N%"` | Text field validated as a percentage |
  | `null` | Text field (empty means null) |
  | `str` whose inline comment lists `a \| b \| c` | Combo box |
  | Other `str` | Text field |

- **Edit semantics**: edits go to an in-memory copy and mark the field and its section as
  "● modified". Parameters are snapshotted at stage start, so edits made during a run apply to the
  next run (an inline note says so). Buttons: **Save to yml**, **Revert**.
- **Save**: the GUI never writes `parameters_cfg.yml` or the shared category profiles.
  - Parameter values are written to a new file,
    `cfgs/profiles/objects/<object_name>_<YYYYMMDD>_<HHMMSS>.yml`. The time part keeps several saves on
    the same day from overwriting each other.
  - The file is a **full snapshot** of everything that defines this object's run, not a diff:
    - `object`: `object_name`, `extension`, `profile`, `parts.num` (all `object_cfg.yml` values
      except `object_profile` itself)
    - every stage section with all of its current values: `transform`, `refine`, `decompose`,
      `segment`, `articulate`, `bind`, `visualization`
    - `pipeline` (stage on/off switches, `debug_mode`, `restore_align`,
      `urdf_use_original_coordinates`) is **excluded**. These are run settings, not object settings.
  - The snapshot is built from a ruamel round-trip copy of `parameters_cfg.yml` with the current values
    written in, so the base file's inline comments (valid ranges, choices) carry over.
  - Each file is self-contained. Older files remain as history and stay selectable.
  - The file starts with a header comment naming the object, the shared profile active at save time,
    and the save time.
  - After writing, only `object_cfg.yml: object_profile` (and `object_name`, if it was changed) is
    updated, through a ruamel round-trip, so comments and key order are preserved. The selector
    switches to the new file.
- Changing `object_name` or `profile` reloads `SystemConfigs` and resets the timeline. This is only
  allowed while idle.

## 8. Timing and minimal mode

`StageTimer` lives in the bridge and is always on:

- Per stage and per step, it records `wall` (step start to next step or stage end) and `wait` (time
  blocked in `interact`/`checkpoint`). `compute = wall − wait`.
- At the end of a run it prints a summary table (stage, compute, wait, wall) and writes
  `working/<object>/attributes/timing.json`:

  ```json
  {"run_started": "...", "minimal": false,
   "stages": {"refine": {"compute": 4.12, "wait": 7.80,
                         "steps": {"poisson": {"compute": 3.10, "wait": 0.0}, ...}}}}
  ```

`--minimal` mode (CLI flag, also a header toggle while idle):

- Viewport rendering is suspended during compute. The last frame stays frozen, and rendering resumes
  only while a scene is mounted.
- Debug checkpoints are forced off.
- Timeline updates are coalesced to 4 Hz.
- The log goes to the terminal only (no stdout tee).
- Interactive stages behave exactly as in full mode.

## 9. Future extension (not built now)

- `ReplayBridge`: answers `interact()` from saved results (`states.json` transform matrix, segment
  owners, articulate joints) and needs no Qt. It enables headless benchmarking with the same
  `StageTimer`. Scene results are plain data so they can be serialized. When this is built, the segment
  stage will also need to persist the fragment → part owner list (it does not today).
- `SingleVectorTarget` for per-arrow mouse manipulation (§6.2).

## 10. Error handling

- An exception inside a stage is caught by the runner. The stage is marked `failed` with the error
  message, the full traceback goes to the log (expanded automatically), and the run stops. The user
  can edit parameters and re-run. The GUI never exits because of a stage error.
- Stop during `interact`/`checkpoint` raises `PipelineStopped` in the worker. The stage is marked
  `stopped`. Stages persist to `states.json` at their end, so a stopped stage leaves the previous state
  intact.
- Closing the window while a run is active asks for confirmation. On confirmation the app requests
  Stop and exits. The worker is a daemon thread.
- Saving yml validates field values before writing. If a write fails, an error is shown and nothing
  is partially written (temp file + replace).
- If Qt/VTK initialization fails, the app exits with a clear message naming the missing package.

## 11. Testing

GUI-free logic checks live in `tests/test_*.py`, one file per module. Each one runs with
`.venv/bin/python -m tests.<name>` (a plain `__main__` runner, so pytest is not required):

- Key/panel inputs produce the expected 4×4 deltas. `AssemblyTarget` composition matches the
  current Align result for the same key sequence.
- View cube piece → camera direction and view-up mapping (face, edge, corner, top/bottom).
- `StageTimer`: `compute = wall − wait` across nested waits.
- `params_io`: widget-type inference; the snapshot contains the `object` block and every stage
  section but no `pipeline`; loading a saved snapshot reproduces the same stage params and object
  values; base comments carry into the snapshot; `object_cfg.yml` keeps its comments and only
  `object_profile` changes; shared files are byte-identical after Save.
- Bridge: `interact` returns the scene result. Stop unblocks a waiting worker with `PipelineStopped`
  (scene resolved from a test thread, no Qt event loop).

Manual smoke checklist (apr_diffuser, real_object profile):

1. Full run with debug on: every checkpoint appears in the viewport, the timeline expands and
   collapses correctly, and the outputs match a pre-change run (same transform/labels/joints for the
   same inputs).
2. Re-run Decompose with a different `threshold`: Segment and later stages turn `stale`, and Run from
   Segment works.
3. `--minimal` run: no checkpoints, terminal-only log, and `timing.json` written.
4. Theme toggle mid-run, the view cube (face, edge, corner), and gizmo drags in Align and Articulate.
5. Stop during Part selection, then Run from Segment.
