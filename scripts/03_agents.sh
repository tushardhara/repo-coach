#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/configs/config.env"
echo "════ AGENTS ════"
cd ~/finetune-workspace
STYLE="Write explanations in normal, clear English."
[ "$CAVEMAN_MODE" = "true" ] && STYLE="Write the EXPLANATION text in caveman speak (short words, no grammar, occasional 'Ugh'). Keep ALL code syntactically correct and normal — never caveman-ify code, variable names, or syntax."

cat > run_agent.sh << INNER
#!/bin/bash
BATCH_FILE="\$1"; OUT="\$2"; PPF="\$3"
FILES=\$(cat "\$BATCH_FILE")
claude -p "You are building a DIVERSE fine-tuning dataset for a code assistant.

Read each of these source files (use your Read tool):
\$FILES

For EACH file, generate exactly \$PPF instruction/response pairs. CRITICAL: maximize diversity — research shows low-diversity synthetic data causes model collapse. Vary BOTH the phrasing and the task type. Across the pairs for each file, cover a spread of:
- explaining what a function/class does
- how to call/use it (with a usage example)
- writing a unit test for it
- refactoring or improving it
- adding error handling
- identifying edge cases or bugs
- comparing two approaches in the file
Vary question phrasing (imperative, question, 'show me', 'why does'). Avoid near-duplicate instructions.

$STYLE

Write results to '\$OUT' as JSONL — ONE json object per line, exact shape:
{\"messages\":[{\"role\":\"user\",\"content\":\"<instruction>\"},{\"role\":\"assistant\",\"content\":\"<response>\"}]}

Use your Write tool to create '\$OUT'. Do not print JSONL to stdout. Reply only with the count of pairs written." \
  --allowedTools "Read,Glob,Grep,Write" --output-format json > "\${OUT}.log" 2>&1
INNER
chmod +x run_agent.sh

AGENTS=$(cat agents/agent_count.txt)
PIDS=()
for i in $(seq 1 $AGENTS); do
  bash run_agent.sh "agents/batch_$i.txt" "agents/dataset_$i.jsonl" "$PAIRS_PER_FILE" &
  PIDS+=($!); echo "Launched agent $i"
done
while :; do
  R=0; for p in "${PIDS[@]}"; do kill -0 "$p" 2>/dev/null && R=$((R+1)); done
  D=0; for i in $(seq 1 $AGENTS); do [ -f "agents/dataset_$i.jsonl" ] && D=$((D+$(wc -l < "agents/dataset_$i.jsonl"|tr -d ' '))); done
  echo -ne "\rRunning: $R | pairs: $D   "; [ "$R" -eq 0 ] && break; sleep 5
done
wait; echo -e "\n✅ Agents done"
