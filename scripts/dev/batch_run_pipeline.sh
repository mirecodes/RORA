#!/usr/bin/env bash
# Dev: run the objects of cfgs/dev/batch_set_cfg.yml in order through the pipeline GUI (README: Dev).
#   [run [object|category]] | status [object|category]
cd "$(dirname "$0")/../.." && exec python -m scripts.dev.run_set batch "$@"
