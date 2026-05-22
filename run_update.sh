#!/bin/bash

cd /home/pedro/.openclaw/workspace
python3 mission-control/scripts/control_queue.py process --max-items 20
python3 mission-control/scripts/build_dashboard_snapshot.py
cd mission-control
git add data/dashboard-data.v2.json data/dashboard-data.json data/control-queue.json data/control-results.jsonl
git diff --cached --quiet || git commit -m "Mission Control snapshot $(date +%F' '%H:%M)"
git push
