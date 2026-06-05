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
import urllib.request
import urllib.error

REPO_COACH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_COACH_ROOT)

_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

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
You analyze source code and create benchmark evaluation questions for a Code Knowledge Graph.
The graph captures: function/method call edges, DB/Redis/queue facts, exposed HTTP routes, and
caller/callee relationships. It does NOT capture: variable values, return types, constant
definitions, test helper internals, or logging field details.
Always reply with a valid JSON array only — no prose, no markdown fences.\
"""

# Question categories aligned to graph tools
_CATEGORY_GUIDE = """\
ALLOWED question categories (graph can answer these):
  CALLERS  — "Which functions call X?" / "What calls into X?"
  CALLEES  — "What does function X call?" / "Which functions does X invoke?"
  DB_ACCESS — "What DB tables / Redis keys / queues does X read or write?"
  ROUTES   — "What HTTP routes does this file expose?"
  FLOW     — "What is the call chain starting from route/handler X?"

BANNED question types (graph cannot answer these — do not generate):
  - What does function X return? (return types not in graph)
  - What are the constants / sentinel errors defined? (graph has no constant nodes)
  - What does a test helper/fake/mock return or contain? (test internals not indexed)
  - What fields does a logger / struct attach? (field-level info not in graph)
  - Why does X do Y? (intent questions)
  - Any question whose answer requires reading variable assignments or literals
"""

def make_prompt(filepath: str, code: str, n: int, symbols: list, facts: list) -> str:
    sym_ctx = ""
    if symbols:
        # only show non-test, non-init symbols to bias toward graph-visible ones
        visible = [s for s in symbols if s.kind in ("function", "method", "route")][:20]
        if visible:
            sym_ctx = "\n\nIndexed symbols (functions/methods/routes):\n" + \
                      "\n".join(f"  - {s.kind}: {s.name}" for s in visible)

    fact_ctx = ""
    if facts:
        fact_ctx = "\n\nIndexed facts (DB/Redis/queue access detected by static analysis):\n" + \
                   "\n".join(f"  - {f.type}: {f.target}" for f in facts[:15])

    has_routes = any(s.kind == "route" for s in symbols)
    has_facts  = bool(facts)
    has_callees = bool(symbols)

    category_hint = []
    if has_routes:
        category_hint.append("ROUTES or FLOW")
    if has_facts:
        category_hint.append("DB_ACCESS")
    if has_callees:
        category_hint.append("CALLERS or CALLEES")
    hint_str = ", ".join(category_hint) if category_hint else "CALLERS or CALLEES"

    return f"""\
File: {filepath}
{sym_ctx}{fact_ctx}

Source code:
{code}

{_CATEGORY_GUIDE}

Generate exactly {n} benchmark questions about this file.
Prefer categories: {hint_str}

Requirements for each question:
- Must be answerable from the INDEXED SYMBOLS and FACTS shown above (not from raw code literals)
- Must name the specific function, route, or table in the question
- Must be one of the ALLOWED categories — if no facts/routes exist, use CALLERS or CALLEES only
- Answer must be 1-2 sentences citing specific function or table names — no preamble

Reply as a JSON array (no markdown fences):
[
  {{"question": "...", "answer": "...", "category": "CALLERS|CALLEES|DB_ACCESS|ROUTES|FLOW"}},
  ...
]"""


def opus_generate(filepath: str, code: str, n: int, symbols: list, facts: list) -> list:
    prompt = make_prompt(filepath, code, n, symbols, facts)
    raw = ""
    try:
        if _ANTHROPIC_KEY:
            payload = json.dumps({
                "model": OPUS_MODEL,
                "max_tokens": 800,
                "system": SYSTEM,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                _ANTHROPIC_URL, data=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": _ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = json.loads(resp.read())["content"][0]["text"].strip()
        else:
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
        print(f"  [warn] opus failed for {filepath}: {e}", file=sys.stderr)
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
                    "category": p.get("category", ""),
                    "messages": [
                        {"role": "user",      "content": p["question"]},
                        {"role": "assistant", "content": p["answer"]},
                    ],
                }
                fh.write(json.dumps(record) + "\n")
                pairs_written += 1
                cat = p.get("category", "")
                print(f"    [{cat}] {p['question'][:85]}")

    print(f"\nWrote {pairs_written} Q&A pairs → {out}")


if __name__ == "__main__":
    main()
