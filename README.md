# RORA

Builds an articulated **URDF** and **per-part Gaussians** from a mesh (`mesh.ply`) and a 3D Gaussian Splatting result (`gaussian.ply`).

```
align → refine → decompose → segment → articulate → bind
align    clean     convex      part        joint       watertight links
         mesh      decomp.     grouping +  suggestion  + URDF
                               vertex      + selection + Gaussian
                               labels                  binding
```

## 1. Install

Python **3.12** recommended.

### uv (recommended)

```bash
git clone <repo-url> RORA
cd RORA
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

### venv

```bash
git clone <repo-url> RORA
cd RORA
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> `submodules/point2mesh` is not needed with the default `refine.method: pymeshlab`.

## 2. Input data

`data/`, `working/`, `export/` are not in git; create them yourself.

```
data/objects/<object_name>/
├── mesh.ply        # object mesh
└── gaussian.ply    # 3DGS result, same frame
```

e.g. `data/objects/apr_diffuser/mesh.ply`, `data/objects/apr_diffuser/gaussian.ply`

## 3. Config

**`cfgs/object_cfg.yml`**: target object.

```yaml
object_name: apr_diffuser   # folder under data/objects/
extension: ply
parts:
  num: 3                    # number of parts the convex fragments are grouped into
profile: real_object        # real_object (real scan) | partnet_object (PartNet synthetic)
```

**`cfgs/parameters_cfg.yml`**: stage parameters. Common keys:

| Key | Description |
|---|---|
| `pipeline.stages.*` | Stage on/off. A stage can be skipped if its result is in `working/`. |
| `pipeline.debug_mode` | Pause at intermediate results in the viewport (ignored with `--minimal`). |
| `refine.method` | `pymeshlab` (default) or `point2mesh`. |
| `decompose.coacd.threshold` | Lower = finer decomposition. |
| `bind.close_holes` | Hole closing per link mesh; a link still open becomes the union of its own CoACD parts (`decompose.coacd`). |
| `bind.suggestion_urdf` | Also write every suggested joint vector, before human selection, to `working/<object>/urdf/` (evaluation `suggest`). |

`cfgs/profiles/<profile>_params_cfg.yml` overrides `parameters_cfg.yml`, only for the keys it lists.
An object profile saved from the GUI (`object_cfg.yml: object_profile`, stored in `cfgs/profiles/objects/`)
is applied last and holds every stage setting for that object.

## 4. Run the pipeline

```bash
source .venv/bin/activate
bash scripts/run_pipeline.sh
# same as
python -m functions.gui.app
```

The pipeline runs in one window: a 3D viewport on the left, and on the right the stage timeline,
the current interaction, the parameters, and the log. Press **▶ Run** to run the enabled stages.
Hover a stage to **↻ re-run** it or **▶ run from** it; edit parameters first to re-run with new values.
**Save object profile** writes every stage setting for this object to
`cfgs/profiles/objects/<object>_<date>_<time>.yml` (shared yml files are never changed).

- **align**: seat the object on z = 0 with Front along +X. Rotate X/Y/Z: `←/→`, `↑/↓`, `Q/E`.
  Move X/Y/Z: `W/S`, `D/A`, `Space/Z`. Or drag the gizmo, or type values in the panel. `Enter`: done.
- **segment (parts)**: pick a part chip (or `Tab`), left click assigns a fragment, right click reverts.
- **articulate (joint axis)**: click an arrow to cycle None → Revolute (amber) → Prismatic (blue);
  `Enter` / **Next pair** moves through the part pairs.
- Everywhere: the view cube (top right) snaps the camera to a face, edge, or corner; `R` resets the view,
  `G` toggles the gizmo.

`bash scripts/run_pipeline.sh --minimal` skips debug pauses and live rendering for timing runs.

### Output

```
export/<object_name>/
├── timing.json                # same as working/.../timing.json (see below)
├── urdf/
│   ├── object.urdf
│   └── meshes/link_*.stl
└── gaussian/gaussian_*.ply    # per-part Gaussians
working/<object_name>/
├── meshes/                    # refined mesh, fragment_*.ply (decompose), links/link_*.ply (bind, watertight)
├── urdf/                      # bind.suggestion_urdf: links fixed to base, one suggest_<a>_<b>_<k> joint per candidate
│   ├── object.urdf
│   └── meshes/link_*.stl
└── attributes/
    ├── states.json            # paths and per-stage results (articulate.joints/suggestions feed bind)
    └── vert_label.npy         # per-vertex part labels of the refined mesh (segment → articulate, bind)
```

Per-stage and per-step timings are printed at the end and saved to `working/<object_name>/attributes/timing.json`
and `export/<object_name>/timing.json` (each run overwrites both; the dev runs in section 6 keep a copy per run):

| Column | Meaning |
|---|---|
| `interact` | the user working in a scene (align, part selection, joint selection) |
| `wait` | a debug checkpoint open until **Continue** (none with `--minimal` or `debug_mode: false`) |
| `compute` | `wall - interact - wait` |
| `wall` | elapsed time |

### Example: rerun some stages

In the GUI, untick stages in the timeline or use ↻ / ▶ on a stage. Without the GUI checkboxes, set
`cfgs/parameters_cfg.yml` to redo only part segmentation:

```yaml
pipeline:
  stages:
    align: false
    refine: false
    decompose: false
    segment: true
    articulate: true
    bind: true
```

align, refine, and decompose must have run once so their results exist in `working/<object_name>/`.

To redo only joint selection with the same part grouping, also set `segment: false`; articulate reloads `attributes/vert_label.npy`.

## 5. (Optional) PartNet-Mobility preprocessing

Merges the part meshes of a PartNet-Mobility URDF, posed by joint offsets, into one pipeline input mesh.

```
data/preprocess/partnet_v0/<name>/mobility.urdf          (input)
        │  apply joint offsets → merge part meshes
        ├─ voxel    → data/objects/<name>/mesh.ply        (pipeline input)
        │             data/objects/<name>/mesh.glb        (same remeshed mesh)
        └─ manifold → data/objects/<name>/mesh_fused.ply  (reference)
```

| Mode | Script | What it does |
|---|---|---|
| `voxel` (default) | `voxel_remeshing.py` | Voxelize → marching cubes → Laplacian smoothing. Always one watertight mesh, even with overlapping or gapped parts. |
| `manifold` | `merge_manifold.py` | Boolean union of part meshes (manifold3d). Keeps exact shape; may break if part meshes aren't closed. |

### 1) Input

Copy the whole PartNet-Mobility object folder to `data/preprocess/partnet_v0/<name>/`, including `mobility.urdf` and the `textured_objs/` it references.

### 2) Config: `cfgs/partnet_v0_preprocessing/partnet_v0_preprocessing_cfg.yml`

Paths are derived from the object name.

```yaml
targets: [faucet]        # objects to process (keys of `objects`)

voxel:
  pitch: 0.02            # voxel size (m). Smaller = more detail, slower.
  rotation_deg: 0        # Z rotation before voxelizing

objects:
  faucet:
    joint_offset: {joint_3: 180}   # joint values applied before merging
  box:                             # empty = rest pose
```

- New object: add it to `objects` and `targets`.
- Joint names (`joint_0`, `joint_1`, ...) match `<joint name=...>` in `mobility.urdf`. Unknown or fixed joints are ignored.
- `joint_offset` units differ: `voxel` reads **degrees** (converted to rad); `manifold` passes values **as-is** (rad for revolute, m for prismatic).

### 3) Run

```bash
source .venv/bin/activate
bash scripts/preprocess_partnet.sh            # voxel → mesh.ply
bash scripts/preprocess_partnet.sh manifold   # manifold → mesh_fused.ply
bash scripts/preprocess_partnet.sh all        # both
```

> `voxel` **overwrites** `data/objects/<name>/mesh.ply`.

### 4) Run the pipeline

1. Preprocessing doesn't create `gaussian.ply`. Put a separately trained 3DGS result at `data/objects/<name>/gaussian.ply`.
2. Edit `cfgs/object_cfg.yml`:
   ```yaml
   object_name: faucet
   profile: partnet_object   # clean mesh: disables Poisson, floor cut, etc. in refine
   ```
3. Run `bash scripts/run_pipeline.sh`.

## 6. Dev: batch and random runs

Development options, not part of the normal pipeline. They run the GUI over a list of objects to rebuild a
test set or to pick objects for a user study. Each list is one yml file that holds, per object, its name,
parts count, and object profile.

| Mode | Script | Object list | Runs |
|---|---|---|---|
| batch | `scripts/dev/batch_run_pipeline.sh` | `cfgs/dev/batch_set_cfg.yml` | the listed objects in order |
| random | `scripts/dev/random_run_pipeline.sh` | `cfgs/dev/random_set_cfg.yml` | `counts` random objects per category, in shuffled order |

```yaml
counts: [1, 1, 0]        # random only: 1 from cat1, 1 from cat2, 0 from cat3
seed: null               # random only: null = new draw each run
defaults: {extension: ply, profile: partnet_object}
objects:
  cat1:
    globe: {parts: 2, object_profile: null}   # object_profile is filled in by the run
```

```bash
source .venv/bin/activate
bash scripts/dev/batch_run_pipeline.sh               # all objects in order
bash scripts/dev/batch_run_pipeline.sh cat2          # one category or one object
bash scripts/dev/random_run_pipeline.sh              # counts / seed from the yml
bash scripts/dev/random_run_pipeline.sh run 1,1,0 7  # override counts and seed
bash scripts/dev/batch_run_pipeline.sh status        # check every object's inputs and outputs
```

- **run** points `cfgs/object_cfg.yml` at each object (name, parts, profile, object profile) and opens the GUI.
  With several objects it asks first: `Enter` run, `s` skip, `q` quit. `object_cfg.yml` is restored at the end.
- After each object, also when the run is cut off with `Ctrl-C`, the run saves that object right away:
  - the object profile you saved in the GUI (and its parts count) is written back to the yml;
  - `working/<object>/` and `export/<object>/` are copied to `working/dev/<date_time>/<object>/` and
    `export/dev/<date_time>/<object>/`, one `<date_time>` per script run. Objects whose pipeline never ran in the
    GUI are not copied.

  ```
  export/dev/20261029_143000/
  ├── session.yml                # mode, counts / seed (random), objects in run order
  ├── batch_set_cfg.yml          # the yml as of the last saved object (parts, object profiles)
  ├── bucket/                    # export/bucket/ at the end of its run: urdf/, gaussian/, timing.json
  └── faucet/
  working/dev/20261029_143000/
  ├── bucket/                    # working/bucket/: meshes/, urdf/ (suggestion URDF), attributes/
  └── faucet/
  ```
- **random** prints the drawn objects and the seed (`counts 1,1,0 seed 7: cat1/globe, cat2/faucet`);
  `run 1,1,0 7` repeats that draw, e.g. to reproduce what a study participant saw.
- **status** prints one line per object: input files, object profile, URDF (parts / moving joints, date),
  per-part Gaussians, and the suggestion URDF. URDF and Gaussian counts must match `parts`. Exits 1 if any object
  is incomplete. It reads the live `export/<object>/` and `working/<object>/`, not a `dev/<date_time>/` copy.
  Check the dates to tell a new run from an old export.
