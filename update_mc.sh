#!/usr/bin/env bash
set -e

# Assumes running from mission-control directory
python3 ../mission-control/scripts/control_queue.py process --max-items 20 || exit 0
python3 ../mission-control/scripts/build_dashboard_snapshot.py || exit 0

git add data/dashboard-data.v2.json data/dashboard-data.json data/control-queue.json data/control-results.jsonl

if git diff --cached --quiet; then
  echo "No changes to commit"
else
  git commit -m "Mission Control snapshot $(date +%F' '%H:%M)"
  git push
fi
