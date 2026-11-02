# Articulation User Study Mode — Design

Date: 2026-10-31
Status: draft, awaiting review

## 1. Goal

Measure how much effort joint authoring takes in the GUI with and without joint suggestions.
Participants articulate pre-segmented PartNet-Mobility-v0 objects in a predefined order under two
conditions:

- **A — no suggestion:** the participant authors every joint by hand from an X/Y/Z triad placed at the
  world origin.
- **B — suggestion:** the participant reviews the suggested vectors in the existing `JointSelectScene`
  (unchanged: no manual add).

Per trial the GUI records elapsed time, mouse clicks split by category (GUI, axis, gizmo, view), key
presses, a timestamped event stream, and the final joints.

Success criteria:

- One command starts a participant session; trials run in the listed order without touching configs.
- Timing covers only the interaction (scene mount → Done); B's suggestion compute is excluded.
- Study runs never write to the regular workflow outputs: everything goes under `export/study/` and
  `working/study/`, one `<timestamp>` folder per run, and `states.json` is only read.
- Final joints of both conditions use the same format (`joints_from_bicons`), so they are directly
  comparable with each other and with PartNet ground truth.

Out of scope: restart-trial and practice-trial buttons, a separate camera-drag category, URDF export of
study joints, automatic counterbalancing, summaries across runs.

## 2. Decisions

| Topic | Decision |
|---|---|
| Host | `--study <file>` mode of the existing GUI (`functions/gui/app.py`), no separate app. |
| Trial order | Listed by hand in a per-participant study file (§3). |
| Condition A input | Triad arrows are clicked to cycle None → Revolute → Prismatic (`cycle_state`), same as B. The triad moves and turns as a whole with the gizmo and the existing keys (`VectorGroupTarget`). |
| Condition A joints | Parent and child are chosen in the panel. One triad at a time: **+ New joint** → adjust → **Confirm joint**. |
| Condition B | `JointSelectScene` as it is today. |
| "Axis" click | A viewport click that hits a joint arrow (changes its type). Moving arrows counts as gizmo or keys. |
| Key count | Every non-auto-repeat `KeyPress` anywhere in the window. Auto-repeat events are kept in the event stream with `repeat: true` but not counted. |
| Outputs | `export/study/<timestamp>/` and `working/study/<timestamp>/` only (§6). One timestamp per run (one `--study` launch) so runs never overwrite each other. |

## 3. Study file

```yaml
# cfgs/study/P01.yml
participant: P01
objects_from: cfgs/dev/batch_set_cfg.yml   # parts / extension / profile / object_profile per object
trials:
  - {object: fan, condition: A}
  - {object: fan, condition: B}
  - {object: box, condition: B}
  - {object: box, condition: A}
```

- `objects_from` reuses the dev manifest format (`defaults` + `objects.<category>.<name>`), read with the
  same `entries()` logic as `scripts/dev/run_set.py`, so object settings are not duplicated.
- Validation at load (before the window opens): unknown object, condition not in `{A, B}`, or missing
  `segment` / `refine` sections in that object's `states.json` → error listing every bad trial.

## 4. Trial flow

1. The window opens in study mode. The header shows `P01 · trial 2/8 · fan · B` and **Start trial ▸**.
   Run/Stop, the timeline, and the parameter editor are hidden; Interaction and Log stay.
2. **Start trial** builds `SystemConfigs` for the object (object profile applied, as `run_set.py` does)
   and starts `study.run_trial(cfgs, condition)` on the existing `PipelineRunner` worker thread.
3. `run_trial` reads the refined mesh and `vert_label` from `states.json` (read-only).
   - **A:** mounts `ManualJointScene(verts, faces, vert_label, parts_num)`.
   - **B:** runs `suggest_bicons(cfgs, verts, faces, vert_label)` (unicons → fusion → unpaired →
     vectors → augmentation, extracted from `stage_articulate` unchanged), then mounts
     `JointSelectScene(bicons, ...)`.
4. The recorder starts when the scene mounts and stops when the scene finishes (Done).
5. `run_trial` converts the result to joints, writes the trial record (§6), and the header switches to
   **Next trial ▸** (or "Session complete" after the last trial).

`stage_articulate` calls `suggest_bicons` too, so the regular pipeline behaviour does not change.

## 5. ManualJointScene (condition A)

Panel (top to bottom):

- **Parent** `[Part k ▾]`, **Child** `[Part k ▾]` (parts `1..parts_num`). When both are set and differ,
  the mesh shows the two parts in color and the rest faded (`label_colors(keep=(p, q))`).
- **+ New joint**: enabled when parent ≠ child and no triad is active. Adds three vectors
  `{center: [0,0,0], n: e_x | e_y | e_z, state: "None"}` and attaches the gizmo to them.
- **Confirm joint**: enabled when at least one triad arrow is Revolute or Prismatic. Stores
  `{parent, child, vectors}` and removes the triad.
- Confirmed joints list: `Parent p → Child c · Revolute (Z)` per entry, with a **✕** to remove one.
- **Done ▸**: finishes the scene. An active, unconfirmed triad is discarded.

Viewport: clicking a triad arrow cycles its state, reusing `state_arrow` colors and `cycle_state`.
Keys/gizmo move the whole triad (`VectorGroupTarget`), so arrows stay orthogonal.

Result: each confirmed joint becomes a pseudo-bicon `{"a": {"src": parent, "dst": child}, "vectors":
[...]}` and the list goes through `joints_from_bicons`, giving the same joint dicts as condition B. The
record also keeps the participant's explicit parent/child per joint (§6), since `joints_from_bicons`
stores the pair as (min, max).

The pure part (triad creation, confirm, remove, pseudo-bicon conversion) lives in `models.py` as
`ManualJoints` so it is testable without Qt/VTK.

## 6. Measurement and outputs

`functions/gui/study.py`: `Recorder` with `start()`, `stop()`, `log(kind, detail="", repeat=False)`.
Times are `time.perf_counter()` seconds since `start()`.

| Category | Source |
|---|---|
| `gui` | Mouse press on any Qt widget that is not the viewport's VTK widget (app-level event filter). |
| `axis` | Viewport press where the scene's `on_pick` handled a joint arrow (`on_pick` returns `bool`). |
| `gizmo` | Viewport press where `gizmo.on_press` returned True. |
| `view` | Viewport press on the view cube or on nothing pickable (camera). |
| `key` | `KeyPress` anywhere in the window (§2). |

The recorder is active only between scene mount and finish, so clicks on **Start trial** / **Next
trial** are not counted.

Output folders (only these are written by study mode). `<timestamp>` is the study file name plus the
run start time, `<study>_YYYYMMDD_HHMMSS` (e.g. `P01_20261102_002632` for `cfgs/study/P01.yml`), fixed
when the study window opens, so every run
gets its own folder:

```
export/study/<timestamp>/
  session.yml                 # whole run: participant, study file, every finished trial's summary
  <object>/<nn>_<cond>.yml    # trial record: counts, time, joints, events
working/study/<timestamp>/
  <object>/<nn>_B_suggestions.json # condition B only: every suggested vector shown (pair, origin, n, final state)
```

`<nn>` is the 1-based trial index in the study file (`02_B.yml`). `session.yml` is rewritten atomically
after every trial, so an interrupted run keeps every finished trial:

```yaml
participant: P01
study_file: cfgs/study/P01.yml
started: 2026-11-03T14:00:02
trials:            # one row per finished trial, in run order (no events)
  - {trial: 1, object: fan, condition: A, duration_s: 95.402,
     counts: {gui: 14, axis: 2, gizmo: 9, view: 18, key: 41}, joints: 1, record: fan/01_A.yml}
totals:            # per condition, over finished trials
  A: {trials: 1, duration_s: 95.402, counts: {gui: 14, axis: 2, gizmo: 9, view: 18, key: 41}}
  B: {trials: 0, duration_s: 0.0, counts: {gui: 0, axis: 0, gizmo: 0, view: 0, key: 0}}
```

Trial record:

```yaml
participant: P01
trial: 2
object: fan
condition: B
started: 2026-11-03T14:02:11
duration_s: 48.213
counts: {gui: 6, axis: 3, gizmo: 4, view: 11, key: 27}
joints:          # joints_from_bicons output; 2+ selected arrows at one origin -> Spherical / Planar
  - {parent: 1, child: 2, type: Revolute, axis: {origin: [0.01, -0.12, 0.30], n: [0.0, 0.0, 1.0]}}
manual_pairs:    # condition A only: participant's explicit parent/child per confirmed joint
  - {parent: 1, child: 2}
events:
  - {t: 0.812, kind: view, detail: ""}
  - {t: 2.140, kind: axis, detail: "Revolute"}
  - {t: 3.020, kind: key, detail: "w", repeat: false}
```

## 7. Changes

| File | Change |
|---|---|
| `functions/gui/study.py` (new) | `load_study(path)`, `Recorder`, `trial_cfgs(entry)`, `run_trial(cfgs, condition, recorder, out)`, trial record and `session.yml` writers. |
| `functions/gui/models.py` | `ManualJoints` (pure triad/confirm/remove/pseudo-bicons). |
| `functions/gui/scenes.py` | `ManualJointScene`; `on_pick` returns `bool` in all scenes. |
| `functions/gui/viewport.py` | Optional `recorder`; `_left_press`/`_right_press` log `gizmo`/`axis`/`view`. |
| `functions/gui/window.py` | Study mode: header (trial label, Start/Next), hide Run/Stop/timeline/editor, app-level event filter for `gui`/`key`. |
| `functions/gui/app.py` | `--study <file>`. |
| `functions/pipeline/articulate.py` | Extract `suggest_bicons(...)`; `stage_articulate` calls it. |
| `tests/test_study.py` (new), `tests/test_models.py`, `tests/test_input_filter.py` (new) | Study file validation, recorder counting (auto-repeat), `ManualJoints` → joints, panel click/key de-duplication, output paths stay under `export/study/<timestamp>/` and `working/study/<timestamp>/`, `session.yml` totals. |
| `cfgs/study/example.yml` (new) | Example study file. |

## 8. Testing

- `tests/test_study.py` as above (no Qt/VTK).
- Smoke: `python -m functions.gui.scenes manual --smoke` mounts `ManualJointScene` on the test box.
- Manual: one A and one B trial on `fan` with `cfgs/study/example.yml`; check the record counts against
  a deliberate sequence of clicks and keys.
