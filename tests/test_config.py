import os
import shutil
import tempfile
from contextlib import contextmanager

from functions.utils import config

ROOT_CFG = config.CFG_DIR


@contextmanager
def temp_cfgs():
    """Copy cfgs/ to a temp dir and point config.CFG_DIR at it."""
    old = config.CFG_DIR
    with tempfile.TemporaryDirectory() as tmp:
        dst = os.path.join(tmp, "cfgs")
        shutil.copytree(ROOT_CFG, dst)
        config.CFG_DIR = dst
        try:
            yield dst
        finally:
            config.CFG_DIR = old


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def test_no_object_profile_is_base_plus_shared_profile():
    with temp_cfgs():
        obj = config.load_object("")
        assert obj["object_profile"] is None
        base = config.load_cfg("parameters_cfg")
        shared = config.load_cfg(f"profiles/{obj['profile']}_params_cfg")
        assert config.load_params(object_profile="") == config._merge(base, shared)


def test_object_profile_overrides_params_and_object_block():
    with temp_cfgs() as d:
        write(os.path.join(d, "profiles", "objects", "toy_20260101_000000.yml"),
              "object:\n  object_name: toy\n  parts:\n    num: 7\n"
              "decompose:\n  coacd:\n    threshold: 0.33\n")
        obj = config.load_object("toy_20260101_000000")
        assert obj["object_name"] == "toy" and obj["parts"]["num"] == 7
        assert obj["object_profile"] == "toy_20260101_000000"
        params = config.load_params(object_profile="toy_20260101_000000")
        assert params["decompose"]["coacd"]["threshold"] == 0.33
        assert "object" not in params
        assert "stages" in params["pipeline"]  # pipeline still comes from the base file


def test_default_reads_object_cfg_and_missing_file_only_warns():
    with temp_cfgs() as d:
        path = os.path.join(d, "object_cfg.yml")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        write(path, text.replace("object_profile: null", "object_profile: missing_stem"))
        assert config.load_object()["object_profile"] == "missing_stem"
        assert config.load_params()["decompose"]["coacd"]  # loads without raising


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
