# RepoCoach — Context Handoff for Claude Code

Paste this whole file into Claude Code as the first message. The code is in `repo-coach/`.

---

## WHAT THIS PROJECT IS

Fine-tunes `Qwen2.5-Coder-1.5B-Instruct` on a specific GitHub repo using MLX LoRA, entirely on Apple Silicon. Result: a fast, private, repo-aware coding assistant served via Ollama.

**Hardware target:** MacBook Pro, Apple Silicon, 18GB unified memory (minimum 8GB).

**Long-term goal:** Fine-tuned model as a cheap local sub-agent under a Claude (Opus/Sonnet) master orchestrator — master handles hard reasoning, small model handles cheap, repetitive, repo-specific tasks.

---

## THE PIPELINE

```
dry_run.sh   → validate toolchain on dummy data (~2 min) — RUN THIS FIRST
run.sh       → orchestrates phases 0-9:
  00 preflight   — check python/git/claude/ollama/hardware
  01 install     — venv + pinned requirements.txt
  02 partition   — clone repo, collect code files, split into batches
  03 agents      — parallel claude -p agents generate DIVERSE training pairs
  04 prepare     — merge/dedupe, 80/10/10 train/valid/test split, auto-size params
  05 download    — fetch base model from HuggingFace
  06 train       — MLX LoRA fine-tune via YAML config (auto batch_size)
  07 fuse        — merge adapter into standalone model
  08 evaluate    — eyeball test on held-out questions
  benchmark.py   — THE SCORE: base vs fine-tuned vs Haiku, LLM-judged → VERDICT
  09 export      — convert to GGUF, register with Ollama
retrain.sh   → smart change-aware retrain (only when >= RETRAIN_MIN_CHANGED_FILES changed)
```

---

## KEY DESIGN DECISIONS (do not regress)

1. **`claude -p` agents MUST include `--allowedTools "Read,Glob,Grep,Write"`** — without it they hang forever on permission prompts.
2. **One agent call per BATCH, not per file** — avoids cold-start overhead; agents read files with their own tools (no bash truncation).
3. **Training uses YAML config** (`configs/lora_config.yaml`), not CLI flags — MLX flag names drift between versions; YAML is stable.
4. **`batch_size` auto-detected from RAM** in `06_train.sh` — 8GB→1, 16GB→2, 24GB→4, 32GB+→8. Prevents OOM kills (exit 137).
5. **Learning rate is 2e-5** (catastrophic forgetting mitigation). Do not raise to 1e-4.
6. **Diversity enforced in agent prompts** — low-diversity synthetic data causes model collapse.
7. **Held-out `test.jsonl`** powers the benchmark — never merge it back into training.
8. **`mlx_lm generate`** (space, not dot) — `mlx_lm.generate` is deprecated in mlx-lm 0.22+.
9. **Fine-tuning teaches patterns, not recall.** For "know my latest code" use retrieval (Continue.dev `@codebase`), not retraining.

---

## VERIFIED ENVIRONMENT

```
mlx:        0.31.2
mlx-lm:     0.30.7
Python:     3.13.5
ollama:     0.5.11
claude CLI: 2.1.150
Hardware:   MacBook Pro, Apple M3 Pro, 18GB
```

---

## WHAT HAS BEEN RUN (flask public test)

- Pipeline ran end-to-end on `pallets/flask` as a public test before the private repo.
- 495 training pairs generated, 397/49/49 train/valid/test split.
- LoRA training: 800 effective iters (resumed from checkpoint after OOM crash, fixed with auto batch_size).
- **VERDICT: NOT YET** — fine-tuned 1.4 vs base 1.4 vs Haiku 2.47.
- Expected: fine-tuning on a public library the base model already knows shows no gain. Private repo will show real delta.

---

## NEXT STEP

Switch to private repo:
```bash
# Edit configs/config.env (gitignored — safe)
REPO_URL="git@github.com:YourOrg/YourRepo.git"
```
Then run:
```bash
bash scripts/dry_run.sh   # 2 min sanity check
bash scripts/run.sh       # full pipeline
```

---

## HONEST RISKS

- `mlx_lm` flag/API can drift with version upgrades — always use YAML config, not CLI flags.
- OOM (exit 137): auto batch_size mitigates this but heavy background apps can still cause it. Close Chrome/Slack before training.
- 1.5B model capacity: expect USEFUL on private code, may still underperform 7B models. Benchmark decides.
- `claude -p` agent quota: uses separate Agent SDK credit pool.

---

## DECISION CRITERION

```
STRONG / USEFUL  → model worth using; proceed toward sub-agent vision
NOT YET          → fine-tuning not paying off; lean on retrieval (@codebase) instead
```

Do not oversell results. Give the honest number.
