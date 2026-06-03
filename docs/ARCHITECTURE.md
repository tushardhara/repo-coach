# Architecture

## Pipeline phases

| Phase | Script | What it does |
|---|---|---|
| 0 | `00_preflight.sh` | Verify python, git, claude, ollama; check hardware |
| 1 | `01_install.sh` | Create venv, install MLX + tools |
| 2 | `02_partition.sh` | Clone repo, collect code files, split into N batches |
| 3 | `03_agents.sh` | Launch parallel Claude Code agents to generate dataset |
| 4 | `04_prepare_data.py` | Merge, dedupe, auto-size training params, split |
| 5 | `05_download.py` | Download base model from HuggingFace |
| 6 | `06_train.sh` | MLX LoRA fine-tuning |
| 7 | `07_fuse.sh` | Fuse LoRA adapter into standalone model |
| 8 | `08_evaluate.py` | Auto-generate repo questions, test the model |
| 9 | `09_export_ollama.sh` | Convert to GGUF, register with Ollama |

## Key design decisions

**One agent call per batch, not per file.** Each `claude -p` invocation has cold-start
overhead. Batching amortizes it and lets the agent read full files with its own tools
instead of bash truncating code.

**Permissions are pre-granted.** Every `claude -p` includes `--allowedTools` so background
agents never hang waiting for an interactive approval.

**Training auto-scales.** `iters` and `num-layers` are derived from dataset size to avoid
overfitting on small repos.

**Two memory mechanisms, not one.** Fine-tuning teaches *patterns* (baked into weights).
Retrieval (`@codebase` in Continue.dev) handles *recall* of specific files. Use both.

## Data flow

```
repo files ──► batches ──► [agent 1..N] ──► dataset_*.jsonl
                                              │
                          merge + dedupe ◄────┘
                                │
                        train.jsonl / valid.jsonl
                                │
                      MLX LoRA ──► adapter ──► fuse ──► model
                                                          │
                                          GGUF ──► Ollama ─┘
```
