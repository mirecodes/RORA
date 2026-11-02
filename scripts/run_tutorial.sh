#!/usr/bin/env bash
# User study tutorial: practice trials before scripts/run_study.sh, with a Skip button (top right) that
# drops the current trial unsaved (results: export/study/<participant>_tutorial_<date_time>/).
#   scripts/run_tutorial.sh P01                 -> cfgs/study/P01/P01_tutorial.yml
#   scripts/run_tutorial.sh cfgs/study/P01/P01_tutorial.yml
cd "$(dirname "$0")/.." || exit 1
if [ $# -lt 1 ]; then
  echo "usage: scripts/run_tutorial.sh <participant | tutorial file>"
  echo "participants:" && ls -d cfgs/study/*/
  exit 1
fi
file="$1"
[ -f "$file" ] || file="cfgs/study/$1/$1_tutorial.yml"
if [ ! -f "$file" ]; then
  echo "[error] no tutorial file '$1' (looked for $1 and cfgs/study/$1/$1_tutorial.yml)"
  exit 1
fi
shift
exec python -m functions.gui.app --study "$file" --tutorial "$@"
