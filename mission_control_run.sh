#!/bin/bash
cd /home/pedro/.openclaw/workspace
python3 mission-control/scripts/control_queue.py process --max-items 20
python3 mission-control/scripts/build_dashboard_snapshot.py
