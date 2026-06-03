#!/bin/bash
# ── RepoCoach — Main Orchestrator ────────────────────────
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/configs/config.env"

echo "🦴 RepoCoach starting..."
echo "Repo: $REPO_URL | Caveman: $CAVEMAN_MODE"
echo ""

bash    "$HERE/scripts/00_preflight.sh"
bash    "$HERE/scripts/01_install.sh"
bash    "$HERE/scripts/02_partition.sh"
bash    "$HERE/scripts/03_agents.sh"
python3 "$HERE/scripts/04_prepare_data.py"
python3 "$HERE/scripts/05_download.py"
bash    "$HERE/scripts/06_train.sh"
bash    "$HERE/scripts/07_fuse.sh"
python3 "$HERE/scripts/08_evaluate.py"
python3 "$HERE/scripts/benchmark.py"          # ← the score
bash    "$HERE/scripts/09_export_ollama.sh"

REPO_NAME=$(basename "$REPO_URL" .git)
echo ""
echo "✅ Done! Check the VERDICT above. Run your model:"
echo "   ollama run ${REPO_NAME}-coder \"How does this project work?\""
