#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/configs/config.env"
echo "════ PREFLIGHT ════"
python3 --version || brew install python@3.11
git --version    || brew install git
claude --version || { echo "❌ Claude Code not found. Install: https://claude.com/claude-code"; exit 1; }
command -v ollama >/dev/null 2>&1 || brew install ollama
system_profiler SPHardwareDataType | grep -E "Chip:|Memory:" || true
df -h ~ | tail -1
[ "$REPO_URL" = "https://github.com/you/your-project.git" ] && { echo "❌ Edit REPO_URL in configs/config.env first."; exit 1; }
echo "✅ Preflight OK"
