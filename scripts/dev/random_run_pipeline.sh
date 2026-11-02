#!/usr/bin/env bash
# Dev: run random objects per category from cfgs/dev/random_set_cfg.yml through the pipeline GUI (README: Dev).
#   [run [n1,n2,n3] [seed]] | status [object|category]
cd "$(dirname "$0")/../.." && exec python -m scripts.dev.run_set random "$@"
