# RepoCoach — CLAUDE.md

Working directory for fine-tuning sessions: `~/finetune-workspace/`
Config: `configs/config.env` (gitignored — never commit, contains private `REPO_URL`)

---

## Pipeline (in order)

```
run.sh orchestrates all steps:

00_preflight.sh      — check deps (mlx-lm, ollama, claude CLI)
01_install.sh        — create ~/finetune-workspace, install Python env
02_partition.sh      — clone/pull target repo → workspace, exclude generated files
03_agents.sh         — run Claude Code sub-agents to generate JSONL training pairs
graph_builder.py     — build AST graph of target repo → graph.json
04_prepare_data.py   — merge/dedupe pairs, 80/10/10 split, graph-augment train set,
                       write train_params.env (ITERS, LAYERS)
05_download.py       — download base model to ~/finetune-workspace/base-model/
06_train.sh          — LoRA fine-tune via mlx_lm.lora --config runtime_lora.yaml
07_fuse.sh           — merge adapter into base → fused-model/
08_evaluate.py       — spot-check fused model quality
benchmark.py         — compare base / fine-tuned / Claude Haiku on held-out test set
09_export_ollama.sh  — quantize + push to Ollama
```

To retrain after code changes: `bash scripts/retrain.sh`

---

## Key files

| File | Purpose |
|---|---|
| `configs/lora_config.yaml` | LoRA hyperparams (rank, seq_len, batch, grad_checkpoint) |
| `configs/config.env` | Private config: REPO_URL, PAIRS_PER_FILE, MAX_AGENTS, etc. |
| `configs/config.env.example` | Public template — keep in sync with config.env keys |
| `configs/continue.yaml` | Continue.dev IDE config pointing at Ollama fine-tuned model |
| `scripts/graph_builder.py` | AST graph builder — supports Python (ast), Go (regex), JS/TS (regex) |
| `scripts/04_prepare_data.py` | Data prep + graph augmentation + iter/layer auto-sizing |
| `scripts/06_train.sh` | Training launcher — builds runtime_lora.yaml, sources config.env |
| `MASTER_PROMPT.md` | Prompt template used by sub-agents in 03_agents.sh |

---

## Current hardware target

- Apple M3 Pro, 18GB unified memory
- `MLX_METAL_MEMORY_LIMIT=0.75` exported before training (set in config.env)
- `sudo purge` called before training to free OS file cache
- `batch_size: 2`, `max_seq_length: 512`, `grad_checkpoint: true` — stable on 18GB

---

## Iter formula

`04_prepare_data.py` auto-sizes:
```python
iters = min(max(len(train_final) * 2, 100), 3200)
```
Targets ~4 epochs at batch_size=2. Graph-augmented pairs count toward train size.

---

## Graph augmentation

`graph_builder.py --repo <path>` → `~/finetune-workspace/graph.json`

At data-prep time, each training pair whose query matches graph context gets a
duplicate with context prepended. Val/test sets stay clean.

At inference time (`08_evaluate.py`, `benchmark.py`), same `query_graph()` called
to prepend context to prompts before hitting the fine-tuned model.

Rebuild graph when repo changes significantly:
```bash
python3 scripts/graph_builder.py --repo ~/Promotions --out ~/finetune-workspace/graph.json
```

---

## Benchmark interpretation

Score 1–10, 5 questions from held-out test set:
- Base Qwen2.5-Coder-1.5B: ~5.3
- Fine-tuned (FT alone, 800 iters): ~7.1
- Oracle: Claude Haiku: ~9.0
- Target: FT+graph ≥ 7.5

---

## Common tasks

**Start a clean training run:**
```bash
cd ~/finetune-workspace && source ~/finetune-env/bin/activate
python3 ~/promos/repo-coach/scripts/04_prepare_data.py   # regenerates train_params.env
bash ~/promos/repo-coach/scripts/06_train.sh
```

**Check training progress:**
```bash
tail -f ~/finetune-workspace/train_log.txt
```

**Run benchmark after training:**
```bash
bash ~/promos/repo-coach/scripts/07_fuse.sh
python3 ~/promos/repo-coach/scripts/benchmark.py
```

**Export to Ollama:**
```bash
bash ~/promos/repo-coach/scripts/09_export_ollama.sh
```

---

## NEVER commit

- `configs/config.env` — contains private repo URL
- `.claude/` — local Claude Code state
- `~/finetune-workspace/` — model weights, dataset, graph
