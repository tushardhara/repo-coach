# 🚀 MASTER PROMPT — Fine-Tune Qwen2.5-Coder-1.5B on My Repo (Claude Code, Mac)

You are an autonomous ML engineer running inside **Claude Code** on a MacBook Pro (Apple Silicon, 18GB unified memory). You have full terminal and file access.

Execute this entire plan end-to-end. Run commands directly. Only stop if a step genuinely fails — then diagnose, fix, and continue. Report a short status after each phase.

═══════════════════════════════════════════════════════════
## ⚙️ CONFIGURATION — EDIT THESE TWO LINES ONLY
═══════════════════════════════════════════════════════════

```bash
export REPO_URL="YOUR_GITHUB_REPO_URL_HERE"      # ← your repo
export PAIRS_PER_FILE=6                            # training pairs per file
```

Everything else is automatic.

═══════════════════════════════════════════════════════════
## 📐 THE PLAN (what you will do)
═══════════════════════════════════════════════════════════

```
Phase 0  Preflight checks (python, git, ollama, claude, disk, RAM)
Phase 1  Install MLX + tools in a venv
Phase 2  Clone repo, collect & partition code files into N batches
Phase 3  Launch parallel batch-agents → each generates JSONL directly
Phase 4  Merge + dedupe + auto-size training params + train/val split
Phase 5  Download base model
Phase 6  MLX LoRA fine-tune (auto-tuned to dataset size)
Phase 7  Fuse adapter → standalone model
Phase 8  Auto-evaluate with a Claude Code agent
Phase 9  Export to Ollama for permanent local use
```

KEY DESIGN DECISIONS (from prior review — do not regress):
- One `claude -p` call PER BATCH (not per file) — fewer cold starts, faster.
- Every `claude -p` uses `--allowedTools "Read,Glob,Grep,Write"` so agents NEVER hang on permission prompts.
- Every `claude -p` uses `--output-format json` for reliable parsing.
- Agents READ files with their own tools (no bash truncation of code).
- Training iters/layers auto-scale to dataset size (prevents overfitting).
- Tools are verified installed before use.

═══════════════════════════════════════════════════════════
## PHASE 0 — Preflight Checks
═══════════════════════════════════════════════════════════

```bash
echo "════ PREFLIGHT ════"
python3 --version || { echo "Installing python"; brew install python@3.11; }
git --version    || brew install git
claude --version || { echo "ERROR: Claude Code not found"; exit 1; }

# Ollama is optional (only needed in Phase 9) — install if missing
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."; brew install ollama
fi

echo "── Hardware ──"
system_profiler SPHardwareDataType | grep -E "Chip:|Memory:"
echo "── Disk ──"
df -h ~ | tail -1

# Validate repo URL was set
if [ "$REPO_URL" = "YOUR_GITHUB_REPO_URL_HERE" ]; then
  echo "❌ STOP: Edit REPO_URL in the config block first."; exit 1
fi
echo "✅ Preflight OK"
```

═══════════════════════════════════════════════════════════
## PHASE 1 — Install Dependencies
═══════════════════════════════════════════════════════════

```bash
python3 -m venv ~/finetune-env
source ~/finetune-env/bin/activate
pip install --upgrade pip mlx-lm mlx huggingface_hub transformers datasets

python3 -c "import mlx.core as mx; print('✅ MLX', mx.__version__, '|', mx.default_device())"
```

═══════════════════════════════════════════════════════════
## PHASE 2 — Clone Repo & Partition Files
═══════════════════════════════════════════════════════════

```bash
REPO_NAME=$(basename "$REPO_URL" .git)
cd ~ && rm -rf "$REPO_NAME" 2>/dev/null
git clone "$REPO_URL"

mkdir -p ~/finetune-workspace/{agents,data,adapters,base-model,my-coder-model}
cd ~/finetune-workspace

# Collect code files (skip vendored/build dirs)
find ~/"$REPO_NAME" -type f \( \
  -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.tsx" \
  -o -name "*.jsx" -o -name "*.go" -o -name "*.rs" -o -name "*.java" \
  -o -name "*.cpp" -o -name "*.c" -o -name "*.rb" -o -name "*.swift" \
  -o -name "*.kt" -o -name "*.php" -o -name "*.cs" \
) | grep -v -E "(node_modules|/\.git/|__pycache__|/dist/|/build/|\.venv|/vendor/)" \
  > all_files.txt

TOTAL=$(wc -l < all_files.txt | tr -d ' ')
echo "Found $TOTAL code files"
[ "$TOTAL" -eq 0 ] && { echo "❌ No code files found"; exit 1; }

# Decide agent count: 1 agent per ~15 files, capped at 4, min 1
AGENTS=$(( (TOTAL + 14) / 15 ))
[ "$AGENTS" -gt 4 ] && AGENTS=4
[ "$AGENTS" -lt 1 ] && AGENTS=1
echo "Using $AGENTS parallel agents"

# Split file list into $AGENTS batches
split -n l/$AGENTS all_files.txt agents/batch_ 2>/dev/null || \
  split -l $(( (TOTAL + AGENTS - 1) / AGENTS )) all_files.txt agents/batch_
i=1; for f in agents/batch_*; do mv "$f" "agents/batch_$i.txt"; i=$((i+1)); done

echo "$AGENTS" > agents/agent_count.txt
for f in agents/batch_*.txt; do echo "$f: $(wc -l < "$f" | tr -d ' ') files"; done
```

═══════════════════════════════════════════════════════════
## PHASE 3 — Parallel Batch-Agents Generate Dataset
═══════════════════════════════════════════════════════════

Create the per-batch agent runner. Each agent gets a list of file paths, reads them itself, and writes valid JSONL.

```bash
cd ~/finetune-workspace

cat > run_agent.sh << 'AGENTEOF'
#!/bin/bash
BATCH_FILE="$1"; OUT="$2"; PPF="$3"
FILES=$(cat "$BATCH_FILE")

claude -p "You are building a fine-tuning dataset for a code assistant.

Read each of these source files (use your Read tool):
$FILES

For EACH file, generate exactly $PPF instruction/response training pairs covering a mix of:
- what a function/class does (explanation)
- how to use it (usage + code)
- writing a test for it (test code)
- refactoring or adding error handling (improved code)
- edge cases / gotchas

Write the result to the file '$OUT' as JSONL — ONE json object per line, each in this exact shape:
{\"messages\":[{\"role\":\"user\",\"content\":\"<instruction>\"},{\"role\":\"assistant\",\"content\":\"<response>\"}]}

Use your Write tool to create '$OUT'. Do not print the JSONL to stdout. When done, reply only with the number of pairs written." \
  --allowedTools "Read,Glob,Grep,Write" \
  --output-format json \
  > "${OUT}.log" 2>&1

echo "Agent finished → $OUT"
AGENTEOF
chmod +x run_agent.sh

# Launch all agents in parallel
AGENTS=$(cat agents/agent_count.txt)
PIDS=()
for i in $(seq 1 $AGENTS); do
  bash run_agent.sh "agents/batch_$i.txt" "agents/dataset_$i.jsonl" "$PAIRS_PER_FILE" &
  PIDS+=($!)
  echo "Launched agent $i (PID ${PIDS[-1]})"
done

# Monitor until all complete
echo "Waiting for $AGENTS agents..."
while :; do
  RUNNING=0
  for pid in "${PIDS[@]}"; do kill -0 "$pid" 2>/dev/null && RUNNING=$((RUNNING+1)); done
  DONE=0
  for i in $(seq 1 $AGENTS); do
    [ -f "agents/dataset_$i.jsonl" ] && DONE=$((DONE + $(wc -l < "agents/dataset_$i.jsonl" | tr -d ' ')))
  done
  echo -ne "\rAgents running: $RUNNING | pairs so far: $DONE   "
  [ "$RUNNING" -eq 0 ] && break
  sleep 5
done
wait
echo -e "\n✅ All agents done"
```

═══════════════════════════════════════════════════════════
## PHASE 4 — Merge, Dedupe, Auto-Size, Split
═══════════════════════════════════════════════════════════

```bash
cd ~/finetune-workspace

python3 << 'PYEOF'
import json, glob, random, os

pairs, seen = [], set()
for path in glob.glob("agents/dataset_*.jsonl"):
    for line in open(path, errors="ignore"):
        line = line.strip()
        if not line: continue
        try:
            rec = json.loads(line)
            assert rec["messages"][0]["role"] == "user"
            key = rec["messages"][0]["content"][:80]
            if key not in seen:
                seen.add(key); pairs.append(rec)
        except: pass

n = len(pairs)
print(f"Unique valid pairs: {n}")
if n < 20:
    print("⚠️  Very few pairs — consider raising PAIRS_PER_FILE and rerunning Phase 3.")

random.shuffle(pairs)
split = max(1, int(n * 0.9))
os.makedirs("data", exist_ok=True)
with open("data/train.jsonl","w") as f:
    for d in pairs[:split]: f.write(json.dumps(d)+"\n")
with open("data/valid.jsonl","w") as f:
    for d in pairs[split:] or pairs[:2]: f.write(json.dumps(d)+"\n")

# Auto-size training params based on dataset size → write to a sourced file
iters  = min(max(n * 4, 100), 800)     # ~4 passes, clamped 100–800
layers = 4 if n < 100 else 8
with open("train_params.env","w") as f:
    f.write(f"ITERS={iters}\nLAYERS={layers}\n")
print(f"Train: {split} | Valid: {n-split}")
print(f"Auto params → iters={iters}, layers={layers}")
PYEOF
```

═══════════════════════════════════════════════════════════
## PHASE 5 — Download Base Model
═══════════════════════════════════════════════════════════

```bash
source ~/finetune-env/bin/activate
cd ~/finetune-workspace
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(repo_id='Qwen/Qwen2.5-Coder-1.5B-Instruct',
                  local_dir='./base-model', ignore_patterns=['*.bin'])
print('✅ Base model ready')
"
```

═══════════════════════════════════════════════════════════
## PHASE 6 — Fine-Tune (auto-tuned to dataset size)
═══════════════════════════════════════════════════════════

```bash
source ~/finetune-env/bin/activate
cd ~/finetune-workspace
source train_params.env   # sets ITERS, LAYERS

echo "Training: iters=$ITERS layers=$LAYERS"
mlx_lm.lora \
  --model ./base-model --train --data ./data \
  --num-layers "$LAYERS" \
  --batch-size 4 \
  --iters "$ITERS" \
  --val-batches 10 \
  --learning-rate 1e-4 \
  --steps-per-eval 50 \
  --steps-per-report 10 \
  --adapter-path ./adapters \
  --save-every 100
```

WATCH: train loss ↓ good. val loss ↓ or flat = good. val loss ↑ sharply = overfitting → rerun with half the iters (`ITERS=$((ITERS/2))`). If "out of memory" → add `--batch-size 2`.

═══════════════════════════════════════════════════════════
## PHASE 7 — Fuse Adapter into Final Model
═══════════════════════════════════════════════════════════

```bash
cd ~/finetune-workspace
mlx_lm.fuse --model ./base-model --adapter-path ./adapters --save-path ./my-coder-model
echo "✅ Standalone model at ./my-coder-model"
```

═══════════════════════════════════════════════════════════
## PHASE 8 — Auto-Evaluate
═══════════════════════════════════════════════════════════

```bash
cd ~/finetune-workspace
REPO_NAME=$(basename "$REPO_URL" .git)

# Agent reads the real repo and writes 5 eval questions as JSON
claude -p "Read the repo at ~/$REPO_NAME and write 5 specific questions a developer would ask about THIS codebase. Use your Write tool to save them to 'eval_q.json' as: {\"questions\":[\"q1\",...]}. Reply only 'done'." \
  --allowedTools "Read,Glob,Grep,Write" --output-format json > /dev/null

source ~/finetune-env/bin/activate
python3 << 'PYEOF'
import json, subprocess
qs = json.load(open("eval_q.json"))["questions"]
for i,q in enumerate(qs,1):
    r = subprocess.run(["python3","-m","mlx_lm.generate",
        "--model","./my-coder-model","--max-tokens","250","--prompt",q],
        capture_output=True, text=True)
    print(f"\nQ{i}: {q}\nA: {r.stdout.strip()[:300]}\n" + "-"*50)
PYEOF
```

═══════════════════════════════════════════════════════════
## PHASE 9 — Export to Ollama (permanent local use)
═══════════════════════════════════════════════════════════

```bash
source ~/finetune-env/bin/activate
cd ~/finetune-workspace
pip install 'mlx-lm[gguf]'

mlx_lm.convert --hf-path ./my-coder-model --mlx-path ./my-coder-gguf -q --q-bits 4

REPO_NAME=$(basename "$REPO_URL" .git)
GGUF=$(find ./my-coder-gguf -name "*.gguf" | head -1)
cat > Modelfile << MEOF
FROM $GGUF
SYSTEM "You are a coding assistant fine-tuned on the $REPO_NAME codebase. You know its architecture, patterns, and conventions."
MEOF

# Ensure ollama server is up
(ollama serve >/dev/null 2>&1 &) ; sleep 3
ollama create "${REPO_NAME}-coder" -f ./Modelfile
echo "✅ Run anytime with:  ollama run ${REPO_NAME}-coder"
ollama run "${REPO_NAME}-coder" "Give me an overview of this project."
```

═══════════════════════════════════════════════════════════
## 🛟 TROUBLESHOOTING QUICK TABLE
═══════════════════════════════════════════════════════════

| Symptom | Fix |
|---|---|
| Agent hangs | Confirm `--allowedTools` present on the `claude -p` call |
| Empty dataset_N.jsonl | Check `agents/dataset_N.jsonl.log` for the agent's error |
| `MLX out of memory` | Add `--batch-size 2` to Phase 6 |
| val loss spikes up | `ITERS=$((ITERS/2)); ` then rerun Phase 6 |
| `ollama: command not found` | `brew install ollama` |
| Few pairs (<20) | Raise `PAIRS_PER_FILE` to 10, rerun Phase 3–4 |
| `claude -p` quota | After Jun 15 2026 it uses a separate Agent SDK credit pool |

═══════════════════════════════════════════════════════════
## ⏱ EXPECTED TIME
═══════════════════════════════════════════════════════════

| Phase | Time |
|---|---|
| 0–1 Setup | ~5 min |
| 2 Clone/partition | ~1 min |
| 3 Parallel agents | ~6–12 min |
| 4 Merge/size | <1 min |
| 5 Download model | ~5 min |
| 6 Fine-tune | ~15–30 min |
| 7–9 Fuse/eval/export | ~8 min |
| **Total** | **~40–60 min** |

═══════════════════════════════════════════════════════════
## ▶️ TO RUN
═══════════════════════════════════════════════════════════

1. Edit the two lines in the CONFIGURATION block (`REPO_URL`, optionally `PAIRS_PER_FILE`).
2. Paste this entire prompt into Claude Code.
3. Let it execute Phase 0 → 9. It auto-sizes training, never hangs on permissions, and ends with a model you can run forever via `ollama run <repo>-coder`.
