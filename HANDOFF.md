# RepoCoach — Context Handoff for Claude Code

Paste this whole file into Claude Code on your laptop as the first message. It contains everything needed to continue the project. The actual code is in the `repo-coach/` folder (extract `repo-coach.tar.gz` first).

---

## WHAT THIS PROJECT IS

RepoCoach fine-tunes a small coding model (`Qwen2.5-Coder-1.5B-Instruct`) on a specific GitHub repo, running entirely on an Apple Silicon Mac. The result is a fast, private, repo-aware coding assistant served via Ollama.

**My hardware:** MacBook Pro, Apple Silicon, 18GB unified memory.

**The long-term goal:** Eventually use this fine-tuned model as a cheap local *sub-agent* under a Claude (Opus/Sonnet) master orchestrator — the master handles hard reasoning, the small local model handles cheap, repetitive, repo-specific tasks. But that's future. **Right now the goal is just: build the model, and benchmark whether it's actually good.**

---

## THE PIPELINE (already built, in `repo-coach/scripts/`)

```
dry_run.sh   → validate toolchain on dummy data (~1-2 min) — RUN THIS FIRST
run.sh       → orchestrates phases 0-9:
  00 preflight   — check python/git/claude/ollama/hardware
  01 install     — venv + pinned requirements.txt
  02 partition   — clone repo, collect code files, split into 1-4 batches
  03 agents      — parallel `claude -p` agents generate DIVERSE training pairs
  04 prepare     — merge/dedupe, 3-way split (train/valid/test), auto-size params
  05 download    — fetch base model
  06 train       — MLX LoRA fine-tune via YAML config (LR 2e-5)
  07 fuse        — merge adapter into standalone model
  08 evaluate    — quick eyeball test
  benchmark.py   — THE SCORE: base vs fine-tuned vs Haiku, LLM-judged, gives verdict
  09 export      — convert to GGUF, register with Ollama
retrain.sh   → smart change-aware retrain (only when enough files changed)
```

---

## KEY DESIGN DECISIONS (do not regress these)

1. **`claude -p` agents MUST include `--allowedTools "Read,Glob,Grep,Write"`** — without it they hang forever on permission prompts in the background.
2. **One agent call per BATCH, not per file** — avoids cold-start overhead, lets agents read full files with their own tools (no bash truncation).
3. **Training uses a YAML config** (`configs/lora_config.yaml`), not CLI flags — MLX flag names drift between versions (`--num-layers` vs `--lora-layers`); YAML is stable.
4. **Learning rate is 2e-5** (research-backed: lowers catastrophic forgetting). Do not raise to 1e-4.
5. **Diversity is enforced in agent prompts** — low-diversity synthetic data causes model collapse.
6. **A held-out `test.jsonl`** the model never trains on powers the benchmark. Don't merge it back into training.
7. **Fine-tuning teaches *patterns*, not recall.** For "know my latest code" we rely on retrieval (Continue.dev `@codebase`), not retraining.

---

## RESEARCH GROUNDING (verified, for context)

- Teacher→student synthetic distillation works; but 1–1.5B models show a real size-performance tradeoff vs 7–8B. The benchmark exists because the 1.5B may underperform.
- 200–500 training pairs = practical minimum for behavior change; 1000+ for style shift.
- LoRA + low LR acts as a regularizer mitigating forgetting.
- `mlx_lm` data format (chat `messages` array) and core commands verified against official MLX docs.

---

## HONEST STATUS & RISKS

- The scripts are **structurally correct but have NOT been run on real Mac hardware.** Expect 2-4 environment/version breakages on first run. They're fixable.
- Most likely break points: `mlx_lm.lora` flag/config compatibility for the installed version; GGUF export quirks; `claude -p --output-format json` envelope shape; the Haiku model string in `benchmark.py`.
- Confidence: benchmark methodology ~90%, first-run reliability ~80%.

---

## WHAT I WANT YOU (Claude Code) TO DO NOW

1. Extract `repo-coach.tar.gz` if not already done.
2. Read the scripts so you understand the pipeline.
3. Edit `configs/config.env` — I'll give you my repo URL (or use a tiny public repo for a first test).
4. **Run `./scripts/dry_run.sh` first.** If it fails, diagnose and fix the actual error (likely a version/flag mismatch — check the installed `mlx_lm` version and adjust `configs/lora_config.yaml` or the command accordingly). Don't work around it silently; tell me what broke and what you changed.
5. Once dry_run passes, run `./scripts/run.sh` and report the benchmark VERDICT.
6. If the verdict is NOT YET, suggest concrete improvements (more pairs, higher diversity, more iters).

Verify commands against current MLX docs rather than assuming flag names. Pause and tell me if anything material differs from what's described here.

---

## MY DECISION CRITERION

The benchmark verdict decides everything:
- **STRONG/USEFUL** → the model is worth using; proceed toward the sub-agent vision.
- **NOT YET** → fine-tuning isn't paying off; I'll lean on retrieval (`@codebase`) instead and reconsider.

Don't oversell results. Give me the honest number.
