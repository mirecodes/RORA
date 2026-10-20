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


def load_params(profile: str | None = None) -> dict:
    """parameters_cfg.yml overlaid with cfgs/profiles/<profile>_params_cfg.yml.
    `profile` defaults to object_cfg.yml's `profile` (null/missing = no overlay)."""
    params = load_cfg("parameters_cfg")
    profile = profile or load_cfg("object_cfg").get("profile")
    if profile:
        params = _merge(params, load_cfg(f"profiles/{profile}_params_cfg"))
    return params


if __name__ == "__main__":
    assert _merge({"a": {"b": 1, "c": 2}, "d": 3}, {"a": {"c": 9}, "e": 4}) == {"a": {"b": 1, "c": 9}, "d": 3, "e": 4}
    assert _merge({"a": {"b": 1}}, {"a": None}) == {"a": None}
    print("ok")
