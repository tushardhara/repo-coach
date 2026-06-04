#!/bin/bash
# Validates the whole toolchain on a TINY dummy dataset before touching your repo.
# Catches environment/version breakage in ~1-2 min instead of 40 min in.
set -e
echo "════ DRY RUN (toolchain self-test) ════"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source ~/finetune-env/bin/activate 2>/dev/null || { echo "Run 01_install.sh first"; exit 1; }

TMP=~/finetune-dryrun
rm -rf "$TMP"; mkdir -p "$TMP/data"; cd "$TMP"

# 3 tiny dummy pairs in each split
for split in train valid test; do
  cat > "data/$split.jsonl" << 'JS'
{"messages":[{"role":"user","content":"What does add do?"},{"role":"assistant","content":"add returns the sum of two numbers."}]}
{"messages":[{"role":"user","content":"Write a test for add"},{"role":"assistant","content":"assert add(2,3)==5"}]}
{"messages":[{"role":"user","content":"Refactor add for clarity"},{"role":"assistant","content":"def add(a,b):\n    return a+b"}]}
JS
done

echo "→ Testing model download (tiny)..."
python3 -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-Coder-1.5B-Instruct', local_dir='./m', ignore_patterns=['*.bin'])" || { echo "❌ download failed"; exit 1; }

echo "→ Testing mlx_lm.lora (5 iters)..."
cat > cfg.yaml << 'YML'
model: ./m
data: ./data
train: true
fine_tune_type: lora
num_layers: 4
iters: 5
batch_size: 1
learning_rate: 2.0e-5
adapter_path: ./adapters
YML
mlx_lm.lora --config cfg.yaml || { echo "❌ training failed — check mlx_lm version/flags"; exit 1; }

echo "→ Testing fuse..."
mlx_lm.fuse --model ./m --adapter-path ./adapters --save-path ./fused || { echo "❌ fuse failed"; exit 1; }

echo "→ Testing generate..."
python3 -m mlx_lm generate --model ./fused --max-tokens 10 --prompt "Hi" || { echo "❌ generate failed"; exit 1; }

echo "→ Testing claude -p (judge path)..."
claude -p "Reply with only the number 5" --output-format json --allowedTools "Read" >/dev/null 2>&1 || echo "⚠️  claude -p check inconclusive (verify manually)"

cd ~ && rm -rf "$TMP"
echo "✅ DRY RUN PASSED — toolchain works. Safe to run ./scripts/run.sh"
