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
  06 train       — MLX LoRA fine-tune via YAML config (auto batch_size from RAM)
  07 fuse        — merge adapter into standalone model
  08 evaluate    — eyeball test on held-out questions
  benchmark.py   — THE SCORE: base vs fine-tuned vs fine-tuned+graph vs Haiku → VERDICT
  09 export      — convert to GGUF, register with Ollama
retrain.sh   → smart change-aware retrain (only when >= RETRAIN_MIN_CHANGED_FILES changed)

graph_builder.py  → standalone RAG graph tool:
  --repo  ~/your-repo  --out ~/finetune-workspace/graph.json   (build)
  --query "how does auth work"                                   (query)
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
10. **`graph_builder.py` supports Python (AST), Go (regex), JS/TS/JSX/TSX (regex).** Skips `.pb.go` generated files. v2 TODO: `all-MiniLM-L6-v2` embeddings (~80MB, runs locally).
11. **`configs/config.env` is gitignored.** Contains private repo URL — NEVER commit. Use `configs/config.env.example` as the template.
12. **`MLX_METAL_MEMORY_LIMIT=0.75`** must be exported before training on 18GB. Set in `config.env`, exported by `06_train.sh`. Prevents Metal OOM that kills the process silently at low iter counts.
13. **`sudo purge` must not block training.** Use `sudo -n purge 2>/dev/null || true` — non-interactive. Or run manually before starting. Without `-n`, a password prompt hangs background jobs silently.
14. **Iter formula: `min(max(train_size * 2, 100), 3200)`** targets ~4 epochs at batch_size=2. Old formula (`n*4, cap 800`) was both under-iterating large sets and producing wrong iter counts.
15. **Graph augmentation trains on context-injected pairs.** For each training pair where `query_graph()` returns context, a duplicate with context prepended is added to train only. Val/test stay clean to avoid data leakage.

---

## VERIFIED ENVIRONMENT

```
mlx:        0.31.2
mlx-lm:     0.30.7
Python:     3.13.5
ollama:     0.5.11
claude CLI: 2.1.150
Hardware:   MacBook Pro, Apple M3 Pro, 18GB

Stable training config (18GB):
  max_seq_length: 512
  batch_size:     2
  rank:           4
  grad_checkpoint: true
  MLX_METAL_MEMORY_LIMIT: 0.75
```

---

## WHAT HAS BEEN RUN (flask public test)

- Pipeline ran end-to-end on `pallets/flask` as a public test before the private repo.
- 495 training pairs generated, 397/49/49 train/valid/test split.
- LoRA training: ~800 effective iters (crashed at iter 200 and 300 due to OOM; resumed from checkpoints; fixed by auto batch_size).
- `graph_builder.py` built for flask: 83 files, 1097 functions, 196 import edges.

**Benchmark history:**

| Date | Dataset | Base | Fine-tuned | FT+Graph | Haiku | Verdict |
|---|---|---|---|---|---|---|
| 2026-06-04 | Flask (public, 495 pairs) | 1.4 | 1.47 | — | 1.73 | expected no gain |
| 2026-06-04 | Promotions (private, 800 iters, 668 pairs) | 5.3 | 7.1 | — | 9.0 | USEFUL |
| pending | Promotions+graph-aug (2138 iters, 1069 pairs) | — | — | — | — | in progress |

Flask showed no gain (base model already knows Flask). Promotions FT (5.3→7.1) confirms private repo fine-tuning works. Graph-augmented run at 2138 iters targets ≥7.5.

---

## NEXT STEP

Switch to private repo:
```bash
# Edit configs/config.env (gitignored — safe)
cp configs/config.env.example configs/config.env
# Set REPO_URL="git@github.com:YourOrg/YourRepo.git"
```

Build the graph for the private repo before benchmarking:
```bash
python3 scripts/graph_builder.py --repo ~/YourRepo --out ~/finetune-workspace/graph.json
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
