"""Dev: run the pipeline GUI over a set of objects listed in cfgs/dev/<mode>_set_cfg.yml.
`python -m scripts.dev.run_set <batch|random> [run|status] ...` (scripts/dev/*_run_pipeline.sh call this)."""
import glob
import os
import random
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import yaml

from functions.gui.params_io import _dump_atomic, _load_rt
from functions.utils import config

OBJ_CFG = os.path.join(config.CFG_DIR, "object_cfg.yml")
MANIFEST = ""  # cfgs/dev/<mode>_set_cfg.yml, set by main()


def entries(doc, which="all"):
    for cat, objs in doc["objects"].items():
        for name, e in objs.items():
            if which in ("all", cat, name):
                yield cat, name, {**doc["defaults"], **e}


def urdf_info(urdf_dir):
    path = next(iter(sorted(glob.glob(os.path.join(urdf_dir, "*.urdf")))), None)
    if not path:
        return None
    root = ET.parse(path).getroot()
    names = [(j.get("name", ""), j.get("type")) for j in root.findall("joint")]
    return {"links": len(root.findall("link")),
            "moving": sum(t != "fixed" and not n.startswith("suggest_") for n, t in names),
            "suggest": sum(n.startswith("suggest_") for n, _ in names),
            "missing": [m.get("filename") for m in root.iter("mesh")
                        if not os.path.isfile(os.path.join(urdf_dir, m.get("filename")))],
            "date": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m-%d %H:%M")}


def check(name, e):
    """[(label, ok, text)]; ok is None for 'not yet' items that are not failures (no snapshot saved)."""
    n, ext, stem = e["parts"], e["extension"], e["object_profile"]
    inp = [f for f in (f"mesh.{ext}", f"gaussian.{ext}") if not os.path.isfile(f"data/objects/{name}/{f}")]
    out = [("input", not inp, "ok" if not inp else "missing " + ",".join(inp))]
    if stem:
        ok = os.path.isfile(os.path.join(config.CFG_DIR, "profiles", "objects", f"{stem}.yml"))
        out.append(("profile", ok, stem if ok else f"{stem} (file missing)"))
    else:
        out.append(("profile", None, "-"))
    u = urdf_info(f"export/{name}/urdf")  # base_link + one link per part, a tree of parts - 1 moving joints
    ok = bool(u) and u["links"] == n + 1 and u["moving"] == n - 1 and not u["missing"]
    out.append(("urdf", ok, f"{u['links'] - 1}P/{u['moving']}J {u['date']}" + (" missing meshes" if u["missing"] else "")
                if u else "none"))
    g = len(glob.glob(f"export/{name}/gaussian/gaussian_*.ply"))
    out.append(("gauss", g == n, str(g)))
    s = urdf_info(f"working/{name}/urdf")
    out.append(("suggest", bool(s) and s["suggest"] > 0 and not s["missing"],
                f"{s['suggest']} cand. {s['date']}" if s else "none"))
    return out


def line(cat, name, e):
    res = check(name, e)
    mark = {True: "✓", False: "✗", None: "·"}
    cells = "  ".join(f"{lab} {mark[ok]} {txt:<{w}}" for (lab, ok, txt), w in zip(res, (2, 28, 22, 2, 18)))
    return f"{cat:<5} {name:<14} parts {e['parts']}  {cells}", all(ok is not False for _, ok, _ in res)


def status(which="all"):
    rows = [line(c, n, e) for c, n, e in entries(_load_rt(MANIFEST), which)]
    for text, _ in rows:
        print(text)
    bad = sum(not ok for _, ok in rows)
    print(f"\n{len(rows) - bad}/{len(rows)} complete (✓ ok, ✗ failed or missing, · no snapshot saved yet)")
    return 1 if bad else 0


def batch_targets(which):
    targets = list(entries(_load_rt(MANIFEST), which))
    if not targets:
        sys.exit(f"[error] no object or category named '{which}' in {MANIFEST}")
    return targets, {"which": which}


def random_targets(counts=None, seed=None):
    """counts like '1,1,0' (default: the cfg's `counts`) -> that many objects drawn per category, in cfg order,
    run in shuffled order. seed defaults to the cfg's `seed`; null draws a new one, printed so it can be repeated."""
    doc = _load_rt(MANIFEST)
    cats = list(doc["objects"])
    ks = [int(k) for k in counts.strip("()").replace(" ", "").split(",")] if counts else list(doc["counts"])
    if len(ks) != len(cats):
        sys.exit(f"[error] {len(ks)} counts for {len(cats)} categories ({', '.join(cats)})")
    seed = doc.get("seed") if seed is None else seed
    seed = random.randrange(10**6) if seed is None else int(seed)
    rng = random.Random(seed)
    targets = []
    for cat, k in zip(cats, ks):
        pool = list(entries(doc, cat))
        if k > len(pool):
            sys.exit(f"[error] {cat} has {len(pool)} objects, asked for {k}")
        targets += rng.sample(pool, k)
    rng.shuffle(targets)
    counts = ",".join(map(str, ks))
    print(f"[info] counts {counts} seed {seed}: " + ", ".join(f"{c}/{n}" for c, n, _ in targets)
          + f"  (repeat with: run {counts} {seed})\n")
    return targets, {"counts": ks, "seed": seed}


def record_snapshot(cat, name, e):
    """object_cfg.yml points at the snapshot the GUI saved last; copy it (and its parts) into the set cfg."""
    stem = _load_rt(OBJ_CFG).get("object_profile")
    if not stem or not re.match(rf"^{re.escape(name)}_\d{{8}}_\d{{6}}(_\d+)?$", stem):
        return
    parts = (config.load_object_profile(stem).get("object") or {}).get("parts", {}).get("num", e["parts"])
    if stem == e["object_profile"] and parts == e["parts"]:
        return
    doc = _load_rt(MANIFEST)
    doc["objects"][cat][name]["object_profile"] = stem
    doc["objects"][cat][name]["parts"] = parts
    _dump_atomic(doc, MANIFEST)
    print(f"[info] {name}: object_profile {e['object_profile']} -> {stem}, parts {e['parts']} -> {parts}")


def archive(name, stamp, since):
    """Copy working/<name> and export/<name> to working/<stamp>/<name> and export/<stamp>/<name> (stamp =
    dev/<date_time>), if the GUI ran the pipeline after `since` (timing.json is written at the end of every run,
    even a stopped one)."""
    timing = f"export/{name}/timing.json"
    if not os.path.isfile(timing) or os.path.getmtime(timing) < since:
        print(f"[info] {name}: the pipeline did not run; nothing saved")
        return
    for root in ("working", "export"):
        shutil.copytree(os.path.join(root, name), os.path.join(root, stamp, name), dirs_exist_ok=True)
    shutil.copy(MANIFEST, os.path.join("export", stamp))  # parts / object_profile as of this object
    print(f"[info] {name}: saved to working/{stamp}/{name}/ and export/{stamp}/{name}/")


def run(mode, targets, info):
    """Point object_cfg.yml at each object and open the GUI. After each object (also on Ctrl-C) record the
    saved snapshot and archive its outputs under <date_time>/; object_cfg.yml is restored at the end."""
    if not targets:
        sys.exit("[error] nothing selected")
    stamp = os.path.join("dev", datetime.now().strftime("%Y%m%d_%H%M%S"))  # -> working/dev/<date_time>/, export/dev/...
    os.makedirs(os.path.join("export", stamp), exist_ok=True)
    with open(os.path.join("export", stamp, "session.yml"), "w", encoding="utf-8") as f:
        yaml.safe_dump({"mode": mode, **info, "objects": [f"{c}/{n}" for c, n, _ in targets]}, f, sort_keys=False)
    print(f"[info] session {stamp}: outputs are saved to working/{stamp}/ and export/{stamp}/\n")
    with open(OBJ_CFG, encoding="utf-8") as f:
        original = f.read()
    try:
        for cat, name, e in targets:
            print(line(cat, name, e)[0])
            if len(targets) > 1:
                ans = input(f"  {name}: [Enter] open GUI, s skip, q quit > ").strip().lower()
                if ans == "q":
                    break
                if ans == "s":
                    continue
            doc = _load_rt(OBJ_CFG)
            doc["object_name"], doc["extension"], doc["profile"] = name, e["extension"], e["profile"]
            doc["parts"]["num"], doc["object_profile"] = e["parts"], e["object_profile"]
            _dump_atomic(doc, OBJ_CFG)
            since = time.time()
            try:
                subprocess.call([sys.executable, "-m", "functions.gui.app"])
            finally:
                record_snapshot(cat, name, e)
                archive(name, stamp, since)
            e = next(entries(_load_rt(MANIFEST), name))[2]
            print(line(cat, name, e)[0] + "\n")
    finally:
        with open(OBJ_CFG, "w", encoding="utf-8") as f:
            f.write(original)


USAGE = {"batch": "batch_run_pipeline.sh [run [object|category]] | status [object|category]",
         "random": "random_run_pipeline.sh [run [n1,n2,n3] [seed]] | status [object|category]"}


def main(argv) -> int:
    global MANIFEST
    if not argv or argv[0] not in USAGE:
        sys.exit(f"usage: python -m scripts.dev.run_set <{'|'.join(USAGE)}> ...")
    mode, cmd, rest = argv[0], (argv[1] if len(argv) > 1 else "run"), argv[2:]
    MANIFEST = os.path.join(config.CFG_DIR, "dev", f"{mode}_set_cfg.yml")
    if cmd == "status":
        return status(rest[0] if rest else "all")
    if cmd == "run" and mode == "batch":
        run(mode, *batch_targets(rest[0] if rest else "all"))
    elif cmd == "run":
        run(mode, *random_targets(*rest[:2]))
    else:
        sys.exit(f"usage: scripts/dev/{USAGE[mode]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
