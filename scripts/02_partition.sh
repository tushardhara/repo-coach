#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/configs/config.env"
echo "════ PARTITION ════"
REPO_NAME=$(basename "$REPO_URL" .git)
cd ~ && rm -rf "$REPO_NAME" 2>/dev/null || true
git clone "$REPO_URL"
mkdir -p ~/finetune-workspace/{agents,data,adapters,base-model,my-coder-model}
cd ~/finetune-workspace
rm -f agents/batch_*.txt agents/dataset_*.jsonl agents/dataset_*.jsonl.log agents/agent_count.txt agents/run_agent.sh 2>/dev/null || true
find ~/"$REPO_NAME" -type f \( \
  -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.tsx" \
  -o -name "*.jsx" -o -name "*.go" -o -name "*.rs" -o -name "*.java" \
  -o -name "*.cpp" -o -name "*.c" -o -name "*.rb" -o -name "*.swift" \
  -o -name "*.kt" -o -name "*.php" -o -name "*.cs" \
\) | grep -v -E "(node_modules|/\.git/|__pycache__|/dist/|/build/|\.venv|/vendor/|\.pb\.go$)" > all_files.txt
TOTAL=$(wc -l < all_files.txt | tr -d ' ')
echo "Found $TOTAL code files"
[ "$TOTAL" -eq 0 ] && { echo "❌ No code files found"; exit 1; }
AGENTS=$(( (TOTAL + 14) / 15 )); [ "$AGENTS" -gt "$MAX_AGENTS" ] && AGENTS=$MAX_AGENTS; [ "$AGENTS" -lt 1 ] && AGENTS=1
echo "$AGENTS" > agents/agent_count.txt
split -n l/$AGENTS all_files.txt agents/batch_ 2>/dev/null || split -l $(( (TOTAL+AGENTS-1)/AGENTS )) all_files.txt agents/batch_
i=1; for f in agents/batch_*; do mv "$f" "agents/batch_$i.txt"; i=$((i+1)); done
echo "Using $AGENTS agents"
