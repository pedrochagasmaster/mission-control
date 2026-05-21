#!/bin/bash
# Daily Git Commit Script for OpenClaw Workspace

set -e

cd /home/pedro/.openclaw/workspace

# Check if there are any changes
if [ -z "$(git status --porcelain)" ]; then
    echo "No changes to commit"
    exit 0
fi

# Configure git if not already set
git config user.email "openclaw@local" || true
git config user.name "OpenClaw Agent" || true

# Stage all changes
git add -A

# Create commit with timestamp
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
git commit -m "Daily sync: $TIMESTAMP"

# Push to origin/main
if git remote get-url origin >/dev/null 2>&1; then
    git push origin main
    echo "Pushed to origin/main"
else
    echo "No remote configured, commit created locally"
fi

echo "Commit completed: $TIMESTAMP"
