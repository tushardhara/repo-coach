#!/usr/bin/env python3
"""
Graph-Context Benchmark — does the Knowledge Graph improve Claude model tiers?

Matrix (6 Claude configs + 1 agent):
  haiku   | no-graph  vs  with-graph
  sonnet  | no-graph  vs  with-graph
  opus    | no-graph  vs  with-graph
  repo-coach agent (Qwen + tool-calling)

Usage:
    python3 scripts/benchmark_models.py [--n 5] [--repo ~/Promotions]

Judge: claude-sonnet-4-6 (pinned, never the candidate itself)
"""
import argparse
import datetime
import json
import os
import statistics
import subprocess
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

# Make repo_coach importable
REPO_COACH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_COACH_ROOT)

WS = os.path.expanduser("~/finetune-workspace")
LOG = os.path.join(WS, "benchmark_models_progress.log")
HISTORY = os.path.join(WS, "benchmark_models_history.log")
DEFAULT_DATASET = os.path.join(WS, "data/benchmark_dataset.jsonl")
TEST_LEGACY = os.path.join(WS, "data/test.jsonl")

DEFAULT_REPO = os.path.expanduser("~/Promotions")
DEFAULT_N = 5

CLAUDE_MODELS = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-7",
}
JUDGE_MODEL = "claude-sonnet-4-6"


def log(msg):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


# ── Graph evidence extraction ─────────────────────────────────────────────────

def extract_graph_evidence(graph, question: str) -> str:
    """Run the planner + first tool + evidence packer. Returns evidence string."""
    from core.navigator.planner import classify_question, suggest_first_tool
    from core.navigator.evidence_packer import (
        pack_flow_evidence, pack_impact_evidence,
        pack_table_evidence, pack_symbol_evidence,
    )

    strategy = classify_question(question)
    first_tool, first_args = suggest_first_tool(question, strategy)

    try:
        result_json = graph.dispatch_tool(first_tool, first_args)
        result = json.loads(result_json)
    except Exception as e:
        return f"[graph error: {e}]"

    if strategy == "flow":
        if isinstance(result, list) and result:
            handler_id = next(
                (r.get("handler_id", "") for r in result
                 if r.get("handler_id") and not _is_setup(r.get("handler_id", ""))),
                ""
            )
            if not handler_id:
                keyword = question.split()[0] if question.split() else "main"
                syms = json.loads(graph.dispatch_tool("find_symbols", {"query": keyword}))
                handler_id = syms[0].get("id", "") if syms else ""
            if handler_id:
                try:
                    flow = json.loads(graph.dispatch_tool("build_flow", {"entrypoint_id": handler_id}))
                    if "error" not in flow:
                        return pack_flow_evidence(question, flow, {}, {})
                except Exception:
                    pass
        return json.dumps(result)[:800]
    elif strategy == "impact":
        if isinstance(result, list) and result:
            sym_id = result[0].get("id", "")
            impact = json.loads(graph.dispatch_tool("build_impact", {"symbol_id": sym_id}))
            return pack_impact_evidence(question, impact)
        return json.dumps(result)[:800]
    elif strategy == "table":
        return pack_table_evidence(question, result if isinstance(result, dict) else {"raw": result})
    else:
        # result is from find_files — file records have no "id".
        # Follow up with find_symbols to get a real symbol, then enrich.
        sym_results = json.loads(graph.dispatch_tool("find_symbols", {"query": question}))
        sym = sym_results[0] if sym_results else {}
        sym_id = sym.get("id", "")

        # If find_symbols found nothing useful, try symbols from the top file
        if not sym_id and isinstance(result, list) and result:
            top_file = result[0].get("file", "")
            if top_file:
                file_syms = json.loads(graph.dispatch_tool("find_symbols", {"query": top_file}))
                sym = file_syms[0] if file_syms else {}
                sym_id = sym.get("id", "")

        callees  = json.loads(graph.dispatch_tool("get_callees", {"symbol_id": sym_id})) if sym_id else []
        callers  = json.loads(graph.dispatch_tool("get_callers", {"symbol_id": sym_id})) if sym_id else []
        facts_raw = json.loads(graph.dispatch_tool("get_facts",  {"symbol_id": sym_id})) if sym_id else []

        base = pack_symbol_evidence(question, sym, callees, callers, facts_raw)

        # Append code snippet for additional grounding
        if sym_id:
            try:
                code_data = json.loads(graph.dispatch_tool("get_code", {"symbol_id": sym_id}))
                snippet = code_data.get("code", "") if isinstance(code_data, dict) else ""
                if snippet:
                    base += f"\n\nCODE ({sym.get('name','')}):\n{snippet[:1200]}"
            except Exception:
                pass

        return base


_SETUP_NAMES = {"setup", "init", "main", "register", "routes", "router"}

def _is_setup(handler_id: str) -> bool:
    name = handler_id.split(":")[-1].lower()
    return any(w in name for w in _SETUP_NAMES)


_ANSWER_INSTRUCTION = (
    "Answer in 1-3 sentences. Name specific functions/tables. No preamble."
)

def build_prompt_with_graph(question: str, evidence: str) -> str:
    return (
        f"Codebase Q&A. {_ANSWER_INSTRUCTION}\n"
        f"Graph evidence below — prefer it when specific, supplement with your knowledge when sparse.\n\n"
        f"GRAPH EVIDENCE:\n{evidence}\n\n"
        f"QUESTION: {question}"
    )

def build_prompt_raw(question: str) -> str:
    return f"Codebase Q&A. {_ANSWER_INSTRUCTION}\n\nQUESTION: {question}"


# ── Anthropic API (direct, no subprocess overhead) ────────────────────────────

_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

def _anthropic(model_id: str, prompt: str, max_tokens: int = 150) -> str:
    if not _ANTHROPIC_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    payload = json.dumps({
        "model": model_id,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        _ANTHROPIC_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": _ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
            return body["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        return f"[error: HTTP {e.code} {e.read().decode()[:120]}]"
    except Exception as e:
        return f"[error: {e}]"


# ── Claude answer ─────────────────────────────────────────────────────────────

def claude_answer(model_id: str, prompt: str) -> str:
    if _ANTHROPIC_KEY:
        return _anthropic(model_id, prompt, max_tokens=150)
    # fallback: subprocess (slow — set ANTHROPIC_API_KEY to avoid)
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--model", model_id, "--output-format", "json"],
            capture_output=True, text=True, timeout=180,
        )
        try:
            return json.loads(r.stdout)["result"].strip()
        except Exception:
            return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return "[error: timeout]"
    except Exception as e:
        return f"[error: {e}]"


# ── Agent answer (repo-coach ask) ─────────────────────────────────────────────

def agent_answer(question: str, repo: str) -> str:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "core.cli.main", "ask", question, "--repo", repo],
            capture_output=True, text=True, timeout=120,
            cwd=REPO_COACH_ROOT,
        )
        out = r.stdout.strip()
        return out or f"[error: {r.stderr.strip()[:200]}]"
    except subprocess.TimeoutExpired:
        return "[error: timeout]"
    except Exception as e:
        return f"[error: {e}]"


# ── Judge ─────────────────────────────────────────────────────────────────────

def judge(question: str, reference: str, candidate: str) -> int:
    if not candidate or candidate.startswith("[error"):
        return 0
    prompt = (
        f"QUESTION: {question}\n"
        f"REFERENCE: {reference}\n"
        f"CANDIDATE: {candidate}\n\n"
        "Score candidate 1-5 vs reference (5=correct, 1=wrong). Reply with ONLY the digit."
    )
    txt = _anthropic(JUDGE_MODEL, prompt, max_tokens=5) if _ANTHROPIC_KEY else ""
    if not txt:
        # fallback subprocess
        try:
            r = subprocess.run(
                ["claude", "-p", prompt, "--model", JUDGE_MODEL, "--output-format", "json"],
                capture_output=True, text=True, timeout=120,
            )
            try:
                txt = json.loads(r.stdout)["result"]
            except Exception:
                txt = r.stdout
        except Exception:
            return 0
    for tok in txt.split():
        t = tok.strip().rstrip(".")
        if t.isdigit():
            return max(1, min(5, int(t)))
    return 0


def avg(xs):
    xs = [x for x in xs if x > 0]
    return round(statistics.mean(xs), 2) if xs else 0.0


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--dataset", default=None,
                        help="Path to Q&A JSONL (default: benchmark_dataset.jsonl, "
                             "fallback: test.jsonl)")
    parser.add_argument("--skip-agent", action="store_true", help="Skip slow Qwen agent")
    args = parser.parse_args()

    repo = os.path.expanduser(args.repo)
    if not os.path.exists(os.path.join(repo, ".repo-coach", "manifest.json")):
        raise SystemExit(f"No index at {repo}/.repo-coach/ — run: repo-coach build {repo}")

    # resolve dataset path
    if args.dataset:
        dataset_path = os.path.expanduser(args.dataset)
    elif os.path.exists(DEFAULT_DATASET):
        dataset_path = DEFAULT_DATASET
    elif os.path.exists(TEST_LEGACY):
        dataset_path = TEST_LEGACY
        log(f"[warn] using legacy test.jsonl — run create_dataset.py for grounded data")
    else:
        raise SystemExit(
            f"No dataset found. Run:\n"
            f"  python3 scripts/create_dataset.py --repo {repo}"
        )
    log(f"Dataset: {dataset_path}")

    # Load graph once
    from core.navigator.graph_tools import GraphStore
    graph = GraphStore(repo)
    log(f"Graph loaded: {len(graph.symbols)} symbols, {len(graph.relations)} relations")

    # Check Ollama
    ollama_ok = False
    if not args.skip_agent:
        try:
            r = subprocess.run(["curl", "-sf", "http://localhost:11434/api/tags"],
                               capture_output=True, text=True, timeout=5)
            ollama_ok = r.returncode == 0
        except Exception:
            pass
    log(f"Ollama: {'UP' if ollama_ok else 'DOWN (agent skipped)'}")

    items = [json.loads(l) for l in open(dataset_path) if l.strip()][:args.n]
    log(f"Benchmarking {len(items)} questions | repo={repo}")
    open(LOG, "a").write("=" * 70 + "\n")

    # score lists: key → list of ints
    configs = [
        ("haiku_raw",    "Haiku    no-graph"),
        ("haiku_graph",  "Haiku  with-graph"),
        ("sonnet_raw",   "Sonnet   no-graph"),
        ("sonnet_graph", "Sonnet with-graph"),
        ("opus_raw",     "Opus     no-graph"),
        ("opus_graph",   "Opus   with-graph"),
    ]
    if ollama_ok:
        configs.append(("agent", "Agent (Qwen tool-call)"))

    scores = {k: [] for k, _ in configs}

    # workers: 6 model calls + 6 judge calls per question run in parallel
    N_WORKERS = 8

    def _answer_and_judge(key: str, model_id: str, prompt: str, q: str, ref: str):
        a = claude_answer(model_id, prompt)
        s = judge(q, ref, a)
        return key, s

    for i, it in enumerate(items, 1):
        q   = it["messages"][0]["content"]
        ref = it["messages"][1]["content"]
        src = it.get("source_file", "")
        cat = it.get("category", "")
        tag = f" [{cat}|{src}]" if src else (f" [{cat}]" if cat else "")
        log(f"\nQ{i}/{len(items)}{tag}: {q[:80]}")

        # Extract graph evidence once per question (fast, local)
        evidence = extract_graph_evidence(graph, q)
        log(f"  Q{i} → evidence: {len(evidence)} chars")

        prompt_raw   = build_prompt_raw(q)
        prompt_graph = build_prompt_with_graph(q, evidence)

        # Fan out all model calls in parallel
        tasks = []
        for model_key, model_id in CLAUDE_MODELS.items():
            tasks.append((f"{model_key}_raw",   model_id, prompt_raw))
            tasks.append((f"{model_key}_graph",  model_id, prompt_graph))
        if ollama_ok:
            tasks.append(("agent", None, None))  # handled separately below

        q_scores = {}
        with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
            futures = {}
            for key, model_id, prompt in tasks:
                if key == "agent":
                    fut = pool.submit(lambda: ("agent", judge(q, ref, agent_answer(q, repo))))
                else:
                    fut = pool.submit(_answer_and_judge, key, model_id, prompt, q, ref)
                futures[fut] = key

            for fut in as_completed(futures):
                try:
                    k, s = fut.result()
                    q_scores[k] = s
                    log(f"  Q{i} → {k}: {s}")
                except Exception as e:
                    log(f"  Q{i} → {futures[fut]}: error ({e})")
                    q_scores[futures[fut]] = 0

        for key, _ in configs:
            scores[key].append(q_scores.get(key, 0))

    # ── Results table ─────────────────────────────────────────────────────────
    log("\n" + "=" * 70)
    log(f"{'CONFIG':<28} {'AVG':>6}  {'SCORES'}")
    log("=" * 70)

    results = {}
    for key, label in configs:
        if key not in scores:
            continue
        a = avg(scores[key])
        results[key] = a
        per_q = "  ".join(str(s) for s in scores[key])
        log(f"  {label:<26} {a:>6}  [{per_q}]")

    log("-" * 70)

    # Graph delta per tier
    for tier in ("haiku", "sonnet", "opus"):
        raw = results.get(f"{tier}_raw", 0)
        gph = results.get(f"{tier}_graph", 0)
        delta = round(gph - raw, 2)
        sign = "+" if delta >= 0 else ""
        log(f"  Graph delta ({tier:6}): {sign}{delta}")

    log("=" * 70)

    # Append history
    record = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "n": len(items), "repo": repo,
        **{k: avg(v) for k, v in scores.items()},
    }
    with open(HISTORY, "a") as fh:
        fh.write(json.dumps(record) + "\n")
    log(f"Appended to {HISTORY}")


if __name__ == "__main__":
    main()
