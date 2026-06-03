#!/bin/bash
# Installs the post-merge retrain hook into your target repo
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/configs/config.env"
REPO_NAME=$(basename "$REPO_URL" .git)
TARGET="$HOME/$REPO_NAME/.git/hooks/post-merge"
cp "$HERE/hooks/post-merge" "$TARGET"
chmod +x "$TARGET"
echo "✅ Installed retrain hook at $TARGET"
echo "   It runs a retrain CHECK after merges into main."
echo "   Actual retrain only fires if >= \$RETRAIN_MIN_CHANGED_FILES changed."
