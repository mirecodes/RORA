#!/usr/bin/env bash
# Run the full object pipeline. Edit functions/pipeline/configs.json to pick the object.
cd "$(dirname "$0")/.." && exec python functions/pipeline/interface.py "$@"
