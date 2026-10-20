#!/usr/bin/env bash
# Launch the pipeline GUI. Settings: cfgs/object_cfg.yml, cfgs/parameters_cfg.yml. Pass --minimal for timing runs.
cd "$(dirname "$0")/.." && exec python -m functions.gui.app "$@"
