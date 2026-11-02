#!/usr/bin/env bash
# User study: run the articulation trials of a study file in the GUI (results: export/study/<date_time>/).
# Run scripts/run_tutorial.sh <participant> first.
#   scripts/run_study.sh P01                    -> cfgs/study/P01/P01.yml
#   scripts/run_study.sh example                -> cfgs/study/example.yml
#   scripts/run_study.sh cfgs/study/P01/P01.yml
cd "$(dirname "$0")/.." || exit 1
if [ $# -lt 1 ]; then
  echo "usage: scripts/run_study.sh <participant | study file>"
  echo "participants:" && ls -d cfgs/study/*/
  exit 1
fi
file="$1"
[ -f "$file" ] || file="cfgs/study/$1/$1.yml"
[ -f "$file" ] || file="cfgs/study/$1.yml"
if [ ! -f "$file" ]; then
  echo "[error] no study file '$1' (looked for $1, cfgs/study/$1/$1.yml and cfgs/study/$1.yml)"
  exit 1
fi
shift
exec python -m functions.gui.app --study "$file" "$@"
