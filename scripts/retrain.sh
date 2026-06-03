#!/bin/bash
# ── RepoCoach — Smart Retrain ────────────────────────────
# Retrains ONLY when meaningful change has accumulated.
# Avoids catastrophic forgetting by always retraining from the
# BASE model on the FULL current dataset (not incremental deltas).
set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/configs/config.env"
REPO_NAME=$(basename "$REPO_URL" .git)
STATE_DIR="$HOME/finetune-workspace/.retrain"
mkdir -p "$STATE_DIR"

# ── Change threshold: how many changed files since last train ──
: "${RETRAIN_MIN_CHANGED_FILES:=10}"

cd ~/"$REPO_NAME" 2>/dev/null || { echo "❌ Repo not cloned. Run scripts/run.sh first."; exit 1; }
git fetch origin >/dev/null 2>&1 || true

LAST_SHA_FILE="$STATE_DIR/last_trained_sha"
CURRENT_SHA=$(git rev-parse HEAD)

if [ -f "$LAST_SHA_FILE" ]; then
  LAST_SHA=$(cat "$LAST_SHA_FILE")
  CHANGED=$(git diff --name-only "$LAST_SHA" "$CURRENT_SHA" 2>/dev/null \
            | grep -E '\.(py|js|ts|tsx|jsx|go|rs|java|cpp|c|rb|swift|kt|php|cs)$' \
            | wc -l | tr -d ' ')
else
  CHANGED=999  # never trained → force
fi

echo "Changed code files since last train: $CHANGED (threshold: $RETRAIN_MIN_CHANGED_FILES)"

if [ "$CHANGED" -lt "$RETRAIN_MIN_CHANGED_FILES" ] && [ "$1" != "--force" ]; then
  echo "⏭  Not enough change to justify retraining. Use --force to override."
  exit 0
fi

echo "🔁 Retraining ${REPO_NAME}-coder from base model on full current dataset..."

# Full clean pipeline from base — prevents forgetting from incremental drift
bash    "$HERE/scripts/02_partition.sh"
bash    "$HERE/scripts/03_agents.sh"
python3 "$HERE/scripts/04_prepare_data.py"
# base model already downloaded; skip 05 unless missing
[ -d "$HOME/finetune-workspace/base-model" ] || python3 "$HERE/scripts/05_download.py"
bash    "$HERE/scripts/06_train.sh"
bash    "$HERE/scripts/07_fuse.sh"
bash    "$HERE/scripts/09_export_ollama.sh"

echo "$CURRENT_SHA" > "$LAST_SHA_FILE"
date '+%Y-%m-%d %H:%M:%S' >> "$STATE_DIR/history.log"
echo "✅ Retrain complete. Model: ${REPO_NAME}-coder"
