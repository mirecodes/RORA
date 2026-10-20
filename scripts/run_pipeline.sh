#!/usr/bin/env bash
# Run the full object pipeline. Settings: cfgs/object_cfg.yml, cfgs/parameters_cfg.yml
cd "$(dirname "$0")/.." && exec python functions/pipeline/interface.py "$@"
