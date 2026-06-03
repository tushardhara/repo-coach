# 🦴 RepoCoach

**Fine-tune a tiny, fast coding model on _your_ GitHub repo — running entirely on your Mac.**

RepoCoach turns `Qwen2.5-Coder-1.5B` into a private, repo-aware coding assistant. It uses **Claude Code sub-agents** to auto-generate the training data, fine-tunes locally with **Apple MLX**, and ships the result to **Ollama** so you can use it forever — offline, free, and fast (~150 tokens/sec on Apple Silicon).

> No training API costs. No code leaves your machine. ~45–60 minutes end to end.

---

## ✨ What you get

- A `your-repo-coder` model in Ollama that knows your codebase's patterns
- Optional **caveman mode** 🦴 (explanations in caveman speak, code stays clean)
- Drop-in **Continue.dev** config for in-editor autocomplete
- Fully automated pipeline — one command

---

## 📋 Requirements

| Requirement | Notes |
|---|---|
| Mac with Apple Silicon (M1–M5) | 16GB+ unified memory recommended |
| [Claude Code](https://claude.com/claude-code) | Generates the training dataset |
| Python 3.10+ | Auto-installed if missing |
| ~10GB free disk | For model + dataset |

---

## 🚀 Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/repo-coach.git
cd repo-coach

# Configure your target repo
export REPO_URL="https://github.com/you/your-project.git"

# (Recommended) verify the toolchain first — ~1-2 min on a tiny dummy dataset
./scripts/dry_run.sh

# Run the whole pipeline (ends with a benchmark score)
./scripts/run.sh
```

The run ends with a **verdict**: whether your fine-tuned model beats base Qwen and Claude Haiku. See [`docs/BENCHMARK.md`](docs/BENCHMARK.md).

When it finishes:

```bash
ollama run your-project-coder "How does the auth module work?"
```

---

## 🧠 How it works

```
Your repo
   │
   ├─► Claude Code sub-agents (parallel) ──► training dataset (JSONL)
   │
   ├─► Apple MLX LoRA fine-tuning ──► adapter
   │
   ├─► fuse ──► standalone model
   │
   └─► export ──► Ollama  ──►  Continue.dev (VS Code autocomplete)
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full breakdown.

---

## ⚙️ Configuration

Edit [`configs/config.env`](configs/config.env):

```bash
REPO_URL="https://github.com/you/your-project.git"
PAIRS_PER_FILE=6          # training examples per source file
CAVEMAN_MODE=false        # set true for 🦴 caveman explanations
BASE_MODEL="Qwen/Qwen2.5-Coder-1.5B-Instruct"
```

---

## 📂 Project structure

```
repo-coach/
├── scripts/
│   ├── run.sh                # main orchestrator (runs all phases)
│   ├── 00_preflight.sh
│   ├── 01_install.sh
│   ├── 02_partition.sh
│   ├── 03_agents.sh          # parallel Claude Code dataset generation
│   ├── 04_prepare_data.py
│   ├── 05_download.py
│   ├── 06_train.sh
│   ├── 07_fuse.sh
│   ├── 08_evaluate.py
│   └── 09_export_ollama.sh
├── configs/
│   ├── config.env            # your settings
│   └── continue.yaml         # Continue.dev config template
├── examples/
│   └── sample_dataset.jsonl
├── docs/
│   ├── ARCHITECTURE.md
│   └── TROUBLESHOOTING.md
├── MASTER_PROMPT.md          # paste-into-Claude-Code version
├── LICENSE
└── README.md
```

---

## 🦴 Caveman mode

Set `CAVEMAN_MODE=true` and the model explains code in caveman speak while keeping code correct:

```
> explain parse_config
parse_config take file. Read settings. Make dict. Give back. Ugh.

def parse_config(path):
    with open(path) as f:
        return json.load(f)
```

---

## 🤝 Contributing

PRs welcome! See [CONTRIBUTING.md](CONTRIBUTING.md). Ideas:
- Support more base models (DeepSeek-Coder, CodeLlama)
- Windows/Linux support (CUDA path)
- VS Code one-click installer

---

## ⚠️ Honest limitations

- A 1.5B model fine-tuned on one repo is **sharp on your code but weaker than Claude/GPT generally**. Use it for fast, small, repo-specific tasks.
- Fine-tuning teaches *patterns*, not perfect recall. For "what's in file X" use retrieval (`@codebase` in Continue.dev), not fine-tuning.
- `claude -p` usage on subscription plans draws from a separate Agent SDK credit pool (as of mid-2026). Check your usage.

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

## 🔁 Retraining

RepoCoach retrains intelligently — only when your codebase's *patterns* actually change, never blindly on every commit (which would waste compute and cause small-model forgetting).

```bash
./scripts/retrain.sh           # retrain if enough changed
./scripts/retrain.sh --force   # retrain now

./scripts/install_hook.sh      # auto-check after merges to main
./scripts/setup_cron.sh        # or weekly check
```

See [`docs/RETRAIN.md`](docs/RETRAIN.md) for the full strategy and why incremental-per-commit training is avoided.
