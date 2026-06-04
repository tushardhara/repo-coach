# Architecture

## Pipeline phases

| Phase | Script | What it does |
|---|---|---|
| 0 | `00_preflight.sh` | Verify python, git, claude, ollama; check hardware |
| 1 | `01_install.sh` | Create venv, install MLX + tools |
| 2 | `02_partition.sh` | Clone repo, collect code files, split into N batches |
| 3 | `03_agents.sh` | Launch parallel Claude Code agents to generate dataset |
| 4 | `04_prepare_data.py` | Merge, dedupe, auto-size training params, 80/10/10 split |
| 5 | `05_download.py` | Download base model from HuggingFace |
| 6 | `06_train.sh` | MLX LoRA fine-tuning (auto batch_size from RAM) |
| 7 | `07_fuse.sh` | Fuse LoRA adapter into standalone model |
| 8 | `08_evaluate.py` | Eyeball test on held-out questions |
| — | `benchmark.py` | Score: base vs fine-tuned vs fine-tuned+graph vs Haiku |
| 9 | `09_export_ollama.sh` | Convert to GGUF, register with Ollama |

### Standalone tools

| Script | What it does |
|---|---|
| `graph_builder.py` | Build AST-based RAG graph; query at inference time |
| `retrain.sh` | Smart change-aware retrain (skips if too few files changed) |
| `dry_run.sh` | 2-minute toolchain sanity check on a tiny dummy dataset |

## Key design decisions

**One agent call per batch, not per file.** Each `claude -p` invocation has cold-start
overhead. Batching amortizes it and lets the agent read full files with its own tools
instead of bash truncating code.

**Permissions are pre-granted.** Every `claude -p` includes `--allowedTools` so background
agents never hang waiting for an interactive approval.

**Training auto-scales.** `iters` and `num_layers` are derived from dataset size to avoid
overfitting on small repos. `batch_size` is derived from system RAM via `sysctl hw.memsize`
(8GB→1, 16GB→2, 24GB→4, 32GB+→8) — prevents OOM kills (exit 137).

**YAML config, not CLI flags.** `mlx_lm` flag names drift between versions. The pipeline
generates `runtime_lora.yaml` at train time with all values injected — stable across upgrades.

**Two memory mechanisms, not one.** Fine-tuning teaches *patterns* (baked into weights).
Retrieval (`@codebase` in Continue.dev, or `graph_builder.py --query`) handles *recall* of
specific files and functions. Use both.

**GraphRAG hybrid.** `benchmark.py` tests a 4th variant: fine-tuned + graph context prepended
to each prompt. If `~/finetune-workspace/graph.json` exists, this column appears automatically.
Use it to measure how much retrieval amplifies fine-tuning.

## Data flow

```
repo files ──► batches ──► [agent 1..N] ──► dataset_*.jsonl
                                              │
                          merge + dedupe ◄────┘
                                │
                   train.jsonl / valid.jsonl / test.jsonl(held-out)
                                │
                  MLX LoRA ──► adapter ──► fuse ──► my-coder-model
                                                          │
              graph_builder.py ──► graph.json             │
                      │                                   │
                      └──► benchmark.py ◄─────────────────┘
                                │
                           GGUF ──► Ollama
```
