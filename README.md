# RORA

Builds an articulated **URDF** and **per-part Gaussians** from a mesh (`mesh.ply`) and a 3D Gaussian Splatting result (`gaussian.ply`).

```
align → refine → decompose → segment → articulate → bind
align    clean     convex      part        joint       Gaussian
         mesh      decomp.     grouping +  suggestion  binding
                               vertex      + selection
                               labels      + URDF
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
| `pipeline.debug_mode` | Show intermediate results in a viewer. |
| `refine.method` | `pymeshlab` (default) or `point2mesh`. |
| `decompose.coacd.threshold` | Lower = finer decomposition. |

`cfgs/profiles/<profile>_params_cfg.yml` overrides `parameters_cfg.yml`, only for the keys it lists.

## 4. Run the pipeline

```bash
source .venv/bin/activate
bash scripts/run_pipeline.sh
# same as
python functions/pipeline/interface.py
```

Some stages open interactive GUI windows. Controls are also printed in the terminal.

- **align**: orient the object Z-up.
  Rotate Z/Y/X: `U/I`, `H/J`, `B/N`. Move X/Y/Z: `W/S`, `D/A`, `Space/Z`. Save: `Q` or `Esc`.
- **segment (parts)**: group convex fragments into parts.
  `Tab` switches part, left click assigns, right click unassigns. Next: `Q` or `Esc`.
- **articulate (joint axis)**: click an arrow to pick the joint type. Once = yellow (revolute), twice = blue (prismatic).

### Output

```
export/<object_name>/
├── urdf/
│   ├── object.urdf
│   └── meshes/link_*.stl
└── gaussian/gaussian_*.ply    # per-part Gaussians
working/<object_name>/
├── meshes/                    # refined mesh, fragment_*.ply (decompose), links/link_*.ply (articulate)
└── attributes/
    ├── states.json            # paths and per-stage results
    └── vert_label.npy         # per-vertex part labels of the refined mesh (segment → articulate, bind)
```

Per-stage timings are printed at the end.

### Example: rerun some stages

To redo only part segmentation, set `cfgs/parameters_cfg.yml`:

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
