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


def test_object_edit_resolution():
    prev = {"object_name": "a", "profile": "real_object", "object_profile": "a_20261020_143012"}
    # editing the object or the shared profile drops the snapshot, which belongs to the old combination
    assert params_io.resolve_object_edit(prev, dict(prev, object_name="b"))["object_profile"] is None
    assert params_io.resolve_object_edit(prev, dict(prev, profile="partnet_object"))["object_profile"] is None
    # picking "(none)" keeps no snapshot; other edits keep the selected one
    assert params_io.resolve_object_edit(prev, dict(prev, object_profile=""))["object_profile"] is None
    assert params_io.resolve_object_edit(prev, dict(prev, extension="obj"))["object_profile"] == "a_20261020_143012"


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
