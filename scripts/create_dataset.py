#!/usr/bin/env python3
"""
Create a grounded benchmark dataset using Claude Opus.

Opus reads actual source files from the Knowledge Graph and generates
factual Q&A pairs about code structure, call flows, and data access.
Other models then answer these questions in benchmark_models.py.

Usage:
    python3 scripts/create_dataset.py --repo ~/Promotions --n 20 --per-file 2
    python3 scripts/create_dataset.py --repo ~/Promotions --out ~/my_dataset.jsonl
"""
import argparse
import json
import os
import random
import subprocess
import sys

REPO_COACH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_COACH_ROOT)

DEFAULT_REPO  = os.path.expanduser("~/Promotions")
DEFAULT_OUT   = os.path.expanduser("~/finetune-workspace/data/benchmark_dataset.jsonl")
DEFAULT_N     = 20   # total questions wanted
DEFAULT_PER   = 2    # questions per file
OPUS_MODEL    = "claude-opus-4-7"
MAX_CODE_CHARS = 6000


# ── File sampling ─────────────────────────────────────────────────────────────

def sample_files(graph, n_files: int) -> list:
    """
    Pick diverse files: top by call-degree centrality, then some random
    for variety.  Returns list of FileRecord objects.
    """
    files = list(graph.files.values())
    if not files:
        return []

    # score by in+out degree
    degree: dict = {}
    for rel in graph.relations:
        if rel.type == "CALLS":
            degree[rel.from_id.split(":")[0] if ":" not in rel.from_id else ":".join(rel.from_id.split(":")[:2])] = \
                degree.get(rel.from_id, 0) + 1
            degree[rel.to_id] = degree.get(rel.to_id, 0) + 1

    # map file path → degree sum
    file_degree: dict = {}
    for sym in graph.symbols.values():
        p = sym.file
        if p:
            file_degree[p] = file_degree.get(p, 0) + degree.get(sym.id, 0)

    ranked = sorted(files, key=lambda f: file_degree.get(f.path, 0), reverse=True)

    # top half by centrality, bottom half random for diversity
    top = ranked[:max(1, n_files // 2)]
    rest = ranked[len(top):]
    rand = random.sample(rest, min(n_files - len(top), len(rest))) if rest else []
    return top + rand


def read_file_code(repo_root: str, rel_path: str) -> str:
    abs_path = os.path.join(repo_root, rel_path)
    if not os.path.exists(abs_path):
        return ""
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as f:
            content = f.read(MAX_CODE_CHARS)
        if len(content) == MAX_CODE_CHARS:
            content += "\n... [truncated]"
        return content
    except Exception:
        return ""


# ── Opus Q&A generation ───────────────────────────────────────────────────────

SYSTEM = """\
You analyze source code and create benchmark evaluation questions.
Your job: generate specific, factual questions whose answers are clearly visible in the code provided.
Always reply with a valid JSON array only — no prose, no markdown fences.\
"""

def make_prompt(filepath: str, code: str, n: int, symbols: list, facts: list) -> str:
    sym_ctx = ""
    if symbols:
        sym_ctx = "\n\nKnown symbols in this file:\n" + \
                  "\n".join(f"  - {s.kind}: {s.name}" for s in symbols[:20])

    fact_ctx = ""
    if facts:
        fact_ctx = "\n\nKnown facts (DB/Redis/queue access):\n" + \
                   "\n".join(f"  - {f.type}: {f.target}" for f in facts[:10])

    return f"""\
File: {filepath}
{sym_ctx}{fact_ctx}

Source code:
{code}

Generate exactly {n} benchmark questions about this file.

Rules:
- Each question must be answerable ONLY from the code/facts above — no guessing
- Cover at least one from each available category: function calls, data access (DB/Redis/queues/HTTP), or route/handler flow
- Name specific functions, tables, routes, or fields in both question and answer
- Avoid "why" or intent questions — only structural/behavioral questions
- Answers should be 2-5 sentences, precise

Reply as a JSON array (no markdown fences):
[
  {{"question": "...", "answer": "..."}},
  ...
]"""


def opus_generate(filepath: str, code: str, n: int, symbols: list, facts: list) -> list:
    prompt = make_prompt(filepath, code, n, symbols, facts)
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--model", OPUS_MODEL,
             "--output-format", "json",
             "--append-system-prompt", SYSTEM],
            capture_output=True, text=True, timeout=120,
        )
        try:
            raw = json.loads(r.stdout)["result"].strip()
        except Exception:
            raw = r.stdout.strip()

        # strip accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        pairs = json.loads(raw)
        if isinstance(pairs, list):
            return [p for p in pairs if isinstance(p, dict)
                    and "question" in p and "answer" in p]
    except Exception as e:
        print(f"  [warn] opus failed for {filepath}: {e}\n  stderr: {r.stderr[:200] if 'r' in dir() else ''}", file=sys.stderr)
    return []


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo",     default=DEFAULT_REPO)
    parser.add_argument("--out",      default=DEFAULT_OUT)
    parser.add_argument("--n",        type=int, default=DEFAULT_N,
                        help="Total questions to generate")
    parser.add_argument("--per-file", type=int, default=DEFAULT_PER,
                        help="Questions per file")
    parser.add_argument("--seed",     type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    repo = os.path.expanduser(args.repo)
    out  = os.path.expanduser(args.out)

    if not os.path.exists(os.path.join(repo, ".repo-coach", "manifest.json")):
        raise SystemExit(f"No index at {repo}/.repo-coach/ — run: repo-coach build {repo}")

    from core.navigator.graph_tools import GraphStore
    graph = GraphStore(repo)
    print(f"Graph loaded: {len(graph.files)} files, {len(graph.symbols)} symbols")

    n_files = max(1, (args.n + args.per_file - 1) // args.per_file)
    sampled = sample_files(graph, n_files)
    print(f"Sampling {len(sampled)} files (want ~{args.n} questions, {args.per_file}/file)")

    os.makedirs(os.path.dirname(out), exist_ok=True)
    pairs_written = 0

    with open(out, "w") as fh:
        for i, frec in enumerate(sampled, 1):
            if pairs_written >= args.n:
                break

            code = read_file_code(repo, frec.path)
            if not code or len(code) < 80:
                continue

            # gather symbols and facts for this file
            file_syms = [s for s in graph.symbols.values() if s.file == frec.path]
            file_facts = []
            for s in file_syms:
                file_facts.extend(graph.facts.get(s.id, []))

            want = min(args.per_file, args.n - pairs_written)
            print(f"  [{i}/{len(sampled)}] {frec.path} — requesting {want} Q&A pairs...")

            pairs = opus_generate(frec.path, code, want, file_syms, file_facts)

            for p in pairs[:want]:
                record = {
                    "source_file": frec.path,
                    "messages": [
                        {"role": "user",      "content": p["question"]},
                        {"role": "assistant", "content": p["answer"]},
                    ],
                }
                fh.write(json.dumps(record) + "\n")
                pairs_written += 1
                print(f"    Q: {p['question'][:90]}")

    print(f"\nWrote {pairs_written} Q&A pairs → {out}")


if __name__ == "__main__":
    main()
