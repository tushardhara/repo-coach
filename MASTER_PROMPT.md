# MASTER PROMPT — Fine-Tune Qwen2.5-Coder-1.5B on My Repo (Claude Code, Mac)

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
## THE PLAN
═══════════════════════════════════════════════════════════

```
Phase 0  Preflight checks (python, git, ollama, claude, disk, RAM)
Phase 1  Install MLX + tools in a venv
Phase 2  Clone repo, collect & partition code files into N batches
Phase 3  Launch parallel batch-agents → each generates JSONL directly
Phase 4  Merge + dedupe + 80/10/10 split + auto-size training params
Phase 5  Download base model
Phase 6  MLX LoRA fine-tune (YAML config, auto batch_size)
Phase 7  Fuse adapter → standalone model
Phase 8  Auto-evaluate on held-out questions
Phase 9  Export to Ollama for permanent local use
```

KEY DESIGN DECISIONS (do not regress):
- One `claude -p` call PER BATCH (not per file) — fewer cold starts, faster.
- Every `claude -p` uses `--allowedTools "Read,Glob,Grep,Write"` so agents NEVER hang.
- Every `claude -p` uses `--output-format json` for reliable parsing.
- Training uses YAML config (`configs/lora_config.yaml`), NOT CLI flags — flag names drift between mlx-lm versions.
- `batch_size` is auto-detected from system RAM — never hardcode it.
- `test.jsonl` is held out from training and used only by `benchmark.py`.
- Use `python3 -m mlx_lm generate` (space, not dot) — `mlx_lm.generate` is deprecated.

═══════════════════════════════════════════════════════════
## PHASE 0 — Preflight Checks
═══════════════════════════════════════════════════════════

```bash
echo "════ PREFLIGHT ════"
python3 --version || { echo "Installing python"; brew install python@3.11; }
git --version    || brew install git
claude --version || { echo "ERROR: Claude Code not found"; exit 1; }
command -v ollama >/dev/null 2>&1 || brew install ollama
echo "── Hardware ──"
system_profiler SPHardwareDataType | grep -E "Chip:|Memory:"
echo "── Disk ──"
df -h ~ | tail -1
[ "$REPO_URL" = "YOUR_GITHUB_REPO_URL_HERE" ] && { echo "❌ STOP: Edit REPO_URL first."; exit 1; }
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

AGENTS=$(( (TOTAL + 14) / 15 ))
[ "$AGENTS" -gt 6 ] && AGENTS=6
[ "$AGENTS" -lt 1 ] && AGENTS=1
echo "Using $AGENTS parallel agents"

split -n l/$AGENTS all_files.txt agents/batch_ 2>/dev/null || \
  split -l $(( (TOTAL + AGENTS - 1) / AGENTS )) all_files.txt agents/batch_
i=1; for f in agents/batch_*; do mv "$f" "agents/batch_$i.txt"; i=$((i+1)); done
echo "$AGENTS" > agents/agent_count.txt
for f in agents/batch_*.txt; do echo "$f: $(wc -l < "$f" | tr -d ' ') files"; done
```

═══════════════════════════════════════════════════════════
## PHASE 3 — Parallel Batch-Agents Generate Dataset
═══════════════════════════════════════════════════════════

```bash
cd ~/finetune-workspace

cat > run_agent.sh << 'AGENTEOF'
#!/bin/bash
BATCH_FILE="$1"; OUT="$2"; PPF="$3"
FILES=$(cat "$BATCH_FILE")

claude -p "You are building a DIVERSE fine-tuning dataset for a code assistant.

Read each of these source files (use your Read tool):
$FILES

For EACH file, generate exactly $PPF instruction/response pairs. CRITICAL: maximize diversity.
Vary BOTH phrasing and task type. Across pairs for each file, cover:
- explaining what a function/class does
- how to call/use it (with usage example)
- writing a unit test for it
- refactoring or improving it
- adding error handling
- identifying edge cases or bugs
- comparing two approaches in the file
Vary question phrasing (imperative, question, 'show me', 'why does'). Avoid near-duplicate instructions.

Write results to '$OUT' as JSONL — ONE json object per line:
{\"messages\":[{\"role\":\"user\",\"content\":\"<instruction>\"},{\"role\":\"assistant\",\"content\":\"<response>\"}]}

Use your Write tool to create '$OUT'. Do not print JSONL to stdout. Reply only with the count." \
  --allowedTools "Read,Glob,Grep,Write" \
  --output-format json \
  > "${OUT}.log" 2>&1

echo "Agent finished → $OUT"
AGENTEOF
chmod +x run_agent.sh

AGENTS=$(cat agents/agent_count.txt)
PIDS=()
for i in $(seq 1 $AGENTS); do
  bash run_agent.sh "agents/batch_$i.txt" "agents/dataset_$i.jsonl" "$PAIRS_PER_FILE" &
  PIDS+=($!)
  echo "Launched agent $i (PID ${PIDS[-1]})"
done

echo "Waiting for $AGENTS agents..."
while :; do
  R=0; for p in "${PIDS[@]}"; do kill -0 "$p" 2>/dev/null && R=$((R+1)); done
  D=0; for i in $(seq 1 $AGENTS); do
    [ -f "agents/dataset_$i.jsonl" ] && D=$((D+$(wc -l < "agents/dataset_$i.jsonl"|tr -d ' ')))
  done
  echo "  agents running: $R | pairs so far: $D"
  [ "$R" -eq 0 ] && break
  sleep 15
done
wait
echo "✅ All agents done"
```

═══════════════════════════════════════════════════════════
## PHASE 4 — Merge, Dedupe, 80/10/10 Split, Auto-Size
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
    print("⚠️  Very few pairs — raise PAIRS_PER_FILE and rerun Phase 3.")

random.shuffle(pairs)
tr = int(n * 0.8); va = int(n * 0.1); te = n - tr - va
os.makedirs("data", exist_ok=True)
with open("data/train.jsonl","w") as f:
    for d in pairs[:tr]: f.write(json.dumps(d)+"\n")
with open("data/valid.jsonl","w") as f:
    for d in pairs[tr:tr+va]: f.write(json.dumps(d)+"\n")
with open("data/test.jsonl","w") as f:
    for d in pairs[tr+va:]: f.write(json.dumps(d)+"\n")

iters  = min(max(n * 4, 100), 800)
layers = 4 if n < 100 else 8
with open("train_params.env","w") as f:
    f.write(f"ITERS={iters}\nLAYERS={layers}\n")
print(f"Train:{tr} | Valid:{va} | Test(held-out):{te}")
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
## PHASE 6 — Fine-Tune (YAML config, auto batch_size)
═══════════════════════════════════════════════════════════

```bash
source ~/finetune-env/bin/activate
cd ~/finetune-workspace
source train_params.env

# Auto batch_size: leave ~40% headroom for OS/GPU/other apps
BATCH=$(python3 -c "
import subprocess
mem = int(subprocess.check_output(['sysctl','-n','hw.memsize']).strip())
gb = mem / 1024**3
print(8 if gb>=32 else 4 if gb>=24 else 2 if gb>=16 else 1)
")
echo "RAM auto-detected → batch_size=$BATCH | iters=$ITERS | layers=$LAYERS"

# Build runtime YAML (never use CLI flags — they drift between mlx-lm versions)
python3 - configs/lora_config.yaml "$ITERS" "$LAYERS" "$BATCH" << 'PYEOF'
import sys, re
tmpl, iters, layers, batch = sys.argv[1:]
cfg = open(tmpl).read()
cfg = re.sub(r'num_layers:.*', f'num_layers: {layers}', cfg, count=1)
cfg = re.sub(r'batch_size:.*', f'batch_size: {batch}', cfg, count=1)
cfg += f"\niters: {iters}\nmodel: ./base-model\ndata: ./data\nadapter_path: ./adapters\ntrain: true\n"
open("runtime_lora.yaml","w").write(cfg)
PYEOF

mlx_lm.lora --config runtime_lora.yaml
```

WATCH: train loss ↓ good. val loss flat or slightly ↑ = normal on small data.
If OOM (exit 137): close Chrome/Slack, then resume from last checkpoint:
```bash
# Resume example (edit checkpoint path and remaining iters):
# Add to runtime_lora.yaml: resume_adapter_file: ./adapters/0000300_adapters.safetensors
# Change iters to remaining count, then re-run: mlx_lm.lora --config runtime_lora.yaml
```

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
source ~/finetune-env/bin/activate
cd ~/finetune-workspace

python3 << 'PYEOF'
import json, subprocess
qs = [r["messages"][0]["content"] for r in
      (json.loads(l) for l in open("data/test.jsonl")) ][:5]
for i,q in enumerate(qs,1):
    r = subprocess.run(
        ["python3","-m","mlx_lm","generate",
         "--model","./my-coder-model","--max-tokens","250","--prompt",q],
        capture_output=True, text=True)
    print(f"\nQ{i}: {q}\nA: {'='*10}\n{r.stdout.strip()[:300]}\n"+"-"*50)
PYEOF
```

═══════════════════════════════════════════════════════════
## BENCHMARK — LLM-Judged Score
═══════════════════════════════════════════════════════════

```bash
source ~/finetune-env/bin/activate
cd ~/finetune-workspace
python3 /path/to/repo-coach/scripts/benchmark.py
```

Scores base vs fine-tuned vs Haiku on 15 held-out questions (1–5 each).
Prints: **STRONG / USEFUL / NOT YET**

═══════════════════════════════════════════════════════════
## PHASE 9 — Export to Ollama
═══════════════════════════════════════════════════════════

```bash
source ~/finetune-env/bin/activate
cd ~/finetune-workspace
pip install 'mlx-lm[gguf]' >/dev/null

mlx_lm.convert --hf-path ./my-coder-model --mlx-path ./my-coder-gguf -q --q-bits 4

REPO_NAME=$(basename "$REPO_URL" .git)
GGUF=$(find ./my-coder-gguf -name "*.gguf" | head -1)
cat > Modelfile << MEOF
FROM $GGUF
SYSTEM "You are a coding assistant fine-tuned on the $REPO_NAME codebase."
MEOF

(ollama serve >/dev/null 2>&1 &) ; sleep 3
ollama create "${REPO_NAME}-coder" -f ./Modelfile
echo "✅ Run: ollama run ${REPO_NAME}-coder"
```

═══════════════════════════════════════════════════════════
## TROUBLESHOOTING
═══════════════════════════════════════════════════════════

| Symptom | Fix |
|---|---|
| Agent hangs | Confirm `--allowedTools` on every `claude -p` call |
| Empty dataset_N.jsonl | Check `agents/dataset_N.jsonl.log` |
| OOM / exit 137 | Close Chrome/Slack; auto batch_size handles this; or resume from checkpoint |
| val loss spikes | Reduce iters by half, retrain |
| `mlx_lm.generate` error | Use `python3 -m mlx_lm generate` (space, not dot) |
| `ollama: command not found` | `brew install ollama` |
| Few pairs (<20) | Raise `PAIRS_PER_FILE` to 10, rerun Phase 3–4 |

═══════════════════════════════════════════════════════════
## EXPECTED TIME
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
## TO RUN
═══════════════════════════════════════════════════════════

1. Copy `configs/config.env.example` → `configs/config.env`, fill in `REPO_URL`.
2. Run `bash scripts/dry_run.sh` first (2 min sanity check).
3. Run `bash scripts/run.sh` — executes Phase 0→9, ends with VERDICT.
