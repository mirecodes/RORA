# User study procedure

One session per participant `Pxx` (P01–P15), in three chapters: **1. Video → 2. Tutorial → 3. Main study**.
Which objects each participant gets, and why, is in [DESIGN.md](cfgs/study/DESIGN.md).

| Chapter | What | Command | Objects |
|---|---|---|---|
| 1 | Video on how the system works | — | — |
| 2 | Tutorial (practice, skippable) | `scripts/run_tutorial.sh Pxx` | 2 (the participant's two categories) × A, B |
| 3 | Main study (recorded) | `scripts/run_study.sh Pxx` | 4 (2 per condition, from two different categories) |

Conditions: **A = manual joints** (the participant places each joint with an X/Y/Z triad),
**B = suggestion-based joints** (the participant picks among suggested joint vectors).

## Participant numbers

- Give participants numbers in the order they come in: the 1st participant is `P01`, the 2nd `P02`, ...,
  the 15th `P15`. Each number is used for one person only. Write down which person has which number,
  and keep that list outside the repo.
- In every command in this document, replace `Pxx` with that participant's number. For example, the
  3rd participant runs:

  ```bash
  scripts/run_tutorial.sh P03
  scripts/run_study.sh P03
  ```

- Each number has a fixed set of objects and a fixed condition order (see the schedule in
  [DESIGN.md](cfgs/study/DESIGN.md)). Only when all 15 numbers are completed is every object tested
  equally often (2 × A, 2 × B), so do not skip numbers or reorder them.
- If a participant drops out or their data cannot be used, give the next new participant the **same**
  number and run the full session again. Keep the old `export/study/Pxx_<date_time>/` folder, but note
  it as excluded.

## Before the session

- Run every command from the repo root.
- Check the participant's files: `cfgs/study/Pxx/Pxx_tutorial.yml` and `cfgs/study/Pxx/Pxx.yml`.
  The comments in each file show the object order and condition of every trial.
- Open the URDF viewer in a browser: <https://gkjohnson.github.io/urdf-loaders/javascript/example/bundle/>.
  To load an object, drag its folder `data/preprocess/partnet_v0/<object>/` (with `mobility.urdf`
  and `textured_objs/`) onto the page.

## 1. Video

Show the participant the video on how the system works: what a joint is, the two conditions (A and B),
and the controls.

## 2. Tutorial

```bash
scripts/run_tutorial.sh Pxx
```

- **Content:** 2 objects, one from each of the two categories the participant gets in the main study.
  Each object is done in condition A and then B, so the order is `obj1 A → obj1 B → obj2 A → obj2 B`.
  None of the tutorial objects come up again in the participant's main study.
- **Before each object:** load that object in the URDF viewer and let the participant move its joints
  until they understand how it is articulated.
- **Concept help:** if the participant is not clear on links (parent/child) or joints, explain as
  needed: which part is the parent and which is the child, where the joint sits, and how a revolute joint
  (rotation about an axis) differs from a prismatic joint (sliding along an axis).
- **Running a trial:** wait until the screen says *Ready*, then press **▶ Start** (top right). The
  participant places the joints and presses **Done ▸**.
- **Skip:** **Skip ▸▸** (top right) drops the current trial without saving it and loads the next one.
  Use it as soon as you judge that the participant understands the task; you can skip several trials in a
  row, up to the end of the tutorial.
- Trials that are completed (not skipped) are saved to `export/study/Pxx_tutorial_<date_time>/`, separate
  from the main study data.

## 3. Main study

```bash
scripts/run_study.sh Pxx
```

- **Content:** 4 objects in two sets of 2. One set uses condition A and the other B; the order (A→B or
  B→A) depends on the participant. The two objects in a set come from different categories, and both sets
  use the same two categories. There is no Skip button.
- **Before each object:** as in the tutorial, let the participant explore the object in the URDF viewer,
  and explain links and joints if they need it.
- **Running a trial:** wait for *Ready*, then press **▶ Start**. The trial is timed from Start until the
  participant presses **Done ▸**. Loading (and computing B's suggestions) is not timed, so do the URDF
  viewer step while the next trial loads.
- **Recorded per trial:** time, click and key counts, and the placed joints.
- **Output:** `export/study/Pxx_<date_time>/`. It has one file per trial (`<object>/<nn>_<A|B>.yml`) and
  `session.yml`, a per-condition summary that is rewritten after every trial. When all trials are done, the
  screen shows *Session complete*.

## During the tutorial and the main study

- Whenever the participant is confused about something (the task, the controls, the object), give them
  the information they need.
- Controls the participant may ask about (also shown on screen): click an arrow to cycle its type
  (None → Revolute → Prismatic); `W/S`, `D/A`, `Space/Z` move along X, Y and Z; arrow keys and `Q/E` rotate;
  `G` toggles the gizmo; `R` resets the view; `Enter` confirms (A) or goes to the next pair (B).

## If an error occurs: restart from that trial

- **The trial fails inside the app** (the screen says *Trial failed*): press **Retry ▸**. That trial
  reloads; trials that were already finished stay saved.
- **The app crashes or closes:** finished trials are already saved, and
  `export/study/Pxx_<date_time>/session.yml` lists them. Restart from the trial where the error happened,
  using a numbered copy of the study file (`Pxx_1`, then `Pxx_2` if it happens again):

  1. Copy the study file. For example, for P01:

     ```bash
     cp cfgs/study/P01/P01.yml cfgs/study/P01/P01_1.yml
     ```

  2. Open `P01_1.yml`. Under `trials:`, delete the object lines **before** the trial where the error
     happened. Keep that trial and everything after it. For example, if the error happened during the
     3rd trial, delete the first 2 `- {object: ..., condition: ...}` lines.
  3. Run the copy. Give the full path, because `scripts/run_study.sh P01_1` does not look inside the
     `P01/` folder:

     ```bash
     scripts/run_study.sh cfgs/study/P01/P01_1.yml
     ```

  The restarted run saves to a new folder, `export/study/P01_1_<date_time>/`, and its trial numbers
  start again at 1. When you analyse the data, combine the two folders and match trials by their object
  and condition fields.
- If the tutorial crashes, just run `scripts/run_tutorial.sh Pxx` again and skip the trials already done.
