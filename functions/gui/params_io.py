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


def resolve_object_edit(prev: dict, edited: dict) -> dict:
    """Object settings after an edit in the Object section. Picking a snapshot restores its object block;
    changing the object or the shared profile drops the snapshot, which belongs to the old combination."""
    stem = edited.get("object_profile") or None
    if stem and stem != (prev.get("object_profile") or None):
        return config.apply_object_profile(edited, stem)
    if edited.get("object_name") != prev.get("object_name") or edited.get("profile") != prev.get("profile"):
        stem = None
    return dict(copy.deepcopy(edited), object_profile=stem)


def list_object_profiles(object_name: str) -> list[str]:
    """Stems of saved profiles for `object_name`, newest first."""
    pattern = re.compile(rf"^{re.escape(object_name)}_\d{{8}}_\d{{6}}(_\d+)?$")
    stems = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(objects_dir(), "*.yml"))]
    return sorted((s for s in stems if pattern.match(s)), reverse=True)
