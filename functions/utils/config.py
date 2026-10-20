import copy
import os

import yaml

CFG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cfgs"))


def load_cfg(name: str) -> dict:
    """Load cfgs/<name>.yml (e.g. 'object_cfg', 'profiles/real_object_params_cfg')."""
    with open(os.path.join(CFG_DIR, f"{name}.yml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _merge(base: dict, override: dict) -> dict:
    """Recursively overlay `override` onto `base` (dicts merge, everything else replaces)."""
    for k, v in override.items():
        base[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base


def load_object_profile(stem: str) -> dict:
    """cfgs/profiles/objects/<stem>.yml (a GUI-saved object snapshot); {} with a warning if missing."""
    path = os.path.join(CFG_DIR, "profiles", "objects", f"{stem}.yml")
    if not os.path.isfile(path):
        print(f"[warn]: object profile not found, skipped: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def apply_object_profile(obj: dict, stem: str | None) -> dict:
    """`obj` overlaid with the snapshot's `object` block (extension, profile, parts). A snapshot saved for
    another object is skipped with a warning, so selecting one can never switch the object being processed."""
    obj = copy.deepcopy(obj)
    obj["object_profile"] = None
    if not stem:
        return obj
    block = load_object_profile(stem).get("object") or {}
    name = block.get("object_name", obj.get("object_name"))
    if name != obj.get("object_name"):
        print(f"[warn]: object profile '{stem}' belongs to '{name}', not '{obj.get('object_name')}'; skipped")
        return obj
    obj = _merge(obj, {k: v for k, v in block.items() if k != "object_name"})
    obj["object_profile"] = stem
    return obj


def object_profile_params(stem: str) -> dict:
    """The stage sections of a snapshot (its `object` block removed)."""
    snapshot = load_object_profile(stem)
    snapshot.pop("object", None)
    return snapshot


def load_object(object_profile: str | None = None) -> dict:
    """object_cfg.yml overlaid with the object profile's `object` block.
    `object_profile`: None = use object_cfg.yml's `object_profile`, "" = none."""
    obj = load_cfg("object_cfg")
    return apply_object_profile(obj, obj.get("object_profile") if object_profile is None else object_profile)


def load_params(profile: str | None = None, object_profile: str | None = None) -> dict:
    """parameters_cfg.yml, then cfgs/profiles/<profile>_params_cfg.yml, then the object profile without
    its `object` block. `profile` defaults to the object's `profile`; `object_profile` as in load_object."""
    obj = load_object(object_profile)
    profile = profile or obj.get("profile")
    params = load_cfg("parameters_cfg")
    if profile:
        params = _merge(params, load_cfg(f"profiles/{profile}_params_cfg"))
    if obj["object_profile"]:
        params = _merge(params, object_profile_params(obj["object_profile"]))
    return params


if __name__ == "__main__":
    assert _merge({"a": {"b": 1, "c": 2}, "d": 3}, {"a": {"c": 9}, "e": 4}) == {"a": {"b": 1, "c": 9}, "d": 3, "e": 4}
    assert _merge({"a": {"b": 1}}, {"a": None}) == {"a": None}
    print("ok")
