# RepoCoach

**A Code Knowledge Agent for your codebase — runs entirely on your Mac.**

RepoCoach builds a structured Code Knowledge Graph of any repo and lets you query it with natural language. It uses Ollama (local) or Claude (API) to answer questions by traversing the graph — never by guessing or loading the whole repo into context.

> No API costs for indexing. No code leaves your machine. Answers grounded in real structure.

---

## What it does

Ask a question → the agent picks the right navigation tool → traverses the Knowledge Graph → answers only from retrieved evidence.

```
$ repo-coach ask "How does voucher assignment flow?" --repo ~/my-repo

Tools used: 2
  find_routes({'query': 'assign'}) -> [{"handler_id": "go:function:routes/assign.go:AssignVoucher"...
  build_flow({'entrypoint_id': 'go:function:routes/assign.go:AssignVoucher'}) -> {"chain": [...

Answer: AssignVoucher validates the coupon via CheckUniqueVoucherReaderDB,
writes to external_voucher_codes, then publishes to the assignment queue.
DB reads: [external_voucher_codes]. DB writes: [voucher_assignments]. Queue: [assign.voucher].
```

---

## Requirements

| Requirement | Notes |
|---|---|
| Mac with Apple Silicon (M1–M5) | 16GB+ unified memory recommended |
| Python 3.10+ | No pip dependencies — stdlib only |
| [Ollama](https://ollama.com) | For local Qwen model (`qwen2.5-coder:1.5b`) |
| [Claude CLI](https://claude.com/claude-code) | Optional — for Haiku/Sonnet/Opus benchmarks |

---

## Quick start

```bash
git clone https://github.com/YOUR_USERNAME/repo-coach.git
cd repo-coach
python3 -m pip install --break-system-packages -e .

# Build the Knowledge Graph for your repo
repo-coach build ~/your-repo

# Ask a question (requires Ollama running)
ollama serve &
ollama pull qwen2.5-coder:1.5b
repo-coach ask "How does the auth flow work?" --repo ~/your-repo
```

---

## How it works

```
Your repo
   │
   └─► repo-coach build    → .repo-coach/ (JSONL Knowledge Graph)
            │
            ├── file_index.jsonl    — every source file + language
            ├── symbols.jsonl       — functions, classes, routes, structs
            ├── relations.jsonl     — CALLS, IMPORTS, EXPOSES_ROUTE, ...
            ├── facts.jsonl         — DB reads/writes, Redis, queues, HTTP calls
            ├── flows.jsonl         — pre-built call chains per route
            └── manifest.json       — build stats
                     │
                     ▼
            repo-coach ask  →  Ollama Qwen (tool-calling agent loop)
                                    │
                     ┌──────────────┴──────────────┐
                     │  Navigation tools (10 total) │
                     │  find_symbols  find_routes   │
                     │  build_flow    build_impact  │
                     │  search_table  get_callees   │
                     │  get_callers   get_facts      │
                     │  get_symbol    get_code       │
                     └─────────────────────────────-┘
```

The agent calls tools in a JSON protocol loop (max 8 calls), accumulates evidence, then writes a grounded answer.

---

## CLI reference

```bash
# Build the index (run once, re-run when code changes significantly)
repo-coach build ~/your-repo

# Ask a natural language question (Qwen agent + tool loop)
repo-coach ask "Who calls CheckUniqueVoucherReaderDB?" --repo ~/your-repo

# Explain a route's full call flow
repo-coach explain --route "POST /assign" ~/your-repo

# Impact analysis — what breaks if this function changes?
repo-coach impact --symbol AssignVoucher ~/your-repo

# DB usage — what reads/writes this table?
repo-coach table external_voucher_codes ~/your-repo

# Debug — show graph evidence without calling Ollama
repo-coach debug-context "How does login work?" ~/your-repo

# Verify Ollama tool-calling is working
repo-coach test-tool-calling ~/your-repo
```

---

## Knowledge Graph

The graph is built from static analysis — no LLM needed for indexing.

| Artifact | Contents |
|---|---|
| Symbols | Functions, methods, classes, structs, interfaces, routes |
| Relations | CALLS, IMPORTS, CONTAINS, EXPOSES_ROUTE, IMPLEMENTS |
| Facts | READS_TABLE, WRITES_TABLE, USES_REDIS, PUBLISHES_QUEUE, CALLS_HTTP |
| Flows | Pre-built BFS call chains from route handlers (max depth 8) |

**Supported languages:** Python (AST), Go (regex), JavaScript/TypeScript (regex).

---

## Benchmark

`scripts/benchmark_models.py` tests the Knowledge Graph as context across Claude model tiers:

```bash
# Requires: repo-coach build ~/Promotions, claude CLI, ollama running
python3 scripts/benchmark_models.py --n 5 --repo ~/Promotions
```

Results on the Promotions codebase (5 questions, judge = claude-sonnet-4-6):

| Config | Avg score (1–5) | Graph delta |
|---|---|---|
| Haiku no-graph | 1.6 | — |
| Haiku + graph | 1.6 | +0.0 |
| Sonnet no-graph | 1.8 | — |
| **Sonnet + graph** | **2.6** | **+0.8** |
| Opus no-graph | 2.6 | — |
| Opus + graph | 2.4 | −0.2 |
| Agent (Qwen 1.5B) | 1.6 | — |

**Sonnet + graph wins.** Opus reasons well without graph context; smaller models can't leverage it.

---

## Project structure

```
repo-coach/
├── core/                     # Python package (stdlib only)
│   ├── cli/                  # CLI commands (main.py, debug_context.py)
│   ├── graph/                # Schema dataclasses
│   ├── scanner/              # File walker + language detection
│   ├── index/                # Build pipeline (builder.py, phase 1–5)
│   ├── parsers/              # Python (AST), Go, JS/TS (regex)
│   ├── resolver/             # CALLS + IMPORTS resolution
│   ├── detectors/            # Routes, SQL, Redis, queues, HTTP, events
│   ├── navigator/            # Graph tools, agent loop, evidence packer
│   └── llm/                  # Ollama client + prompts
├── scripts/
│   ├── benchmark_agent.py    # repo-coach ask vs Haiku (5 questions)
│   └── benchmark_models.py   # graph context across Haiku/Sonnet/Opus
├── setup.py
└── README.md
```

---

## Configuration

```bash
# Use a different Ollama model
export REPO_COACH_MODEL=qwen2.5-coder:7b
repo-coach ask "..." --repo ~/your-repo

# Build is verbose by default; suppress with --no-verbose if needed
repo-coach build ~/your-repo
```

---

## Honest limitations

- **"Why" questions score low** — the graph answers *structure* (how, what, who calls what). Questions about intent and history require reading commit messages or comments, not graph traversal.
- **Go route aliases** — `Handler = pkg.Func` alias patterns can't be resolved without tree-sitter. The agent falls back to compound keyword search.
- **Qwen 1.5B tool-calling** — small model sometimes fails to follow the JSON tool-call protocol. Sonnet + graph context (direct, no agent loop) outperforms the agent on hard questions.
- **Regex parsers** — Go and JS/TS use regex (tree-sitter not installed by default). Accuracy is ~0.7 vs AST's 1.0.

---

## License

MIT — see [LICENSE](LICENSE).
