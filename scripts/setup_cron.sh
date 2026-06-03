#!/bin/bash
# Sets up a weekly retrain check (Sundays 2am)
HERE="$(cd "$(dirname "$0")/.." && pwd)"
LINE="0 2 * * 0 bash $HERE/scripts/retrain.sh >> $HOME/finetune-workspace/.retrain/cron.log 2>&1"
( crontab -l 2>/dev/null | grep -v "retrain.sh"; echo "$LINE" ) | crontab -
echo "✅ Weekly retrain check scheduled (Sundays 2am)."
echo "   Remove with: crontab -e"
