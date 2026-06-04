#!/usr/bin/env python3
"""
RepoCoach Agent Benchmark — does the new Code Knowledge Agent beat Haiku?

Tests the repo-coach ask CLI (Ollama Qwen + tool-calling loop) against
Claude Haiku on held-out test.jsonl questions.

Usage:
    python3 scripts/benchmark_agent.py [--n 5] [--repo ~/Promotions]

Requires:
    ollama serve  (in another terminal)
    ollama pull qwen2.5-coder:1.5b
    repo-coach build ~/Promotions  (index must exist)
"""
import argparse
import datetime
import json
import os
import statistics
import subprocess
import sys

WS = os.path.expanduser("~/finetune-workspace")
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(WS, "benchmark_agent_progress.log")
HISTORY = os.path.join(WS, "benchmark_agent_history.log")
TEST = os.path.join(WS, "data/test.jsonl")

DEFAULT_REPO = os.path.expanduser("~/Promotions")
DEFAULT_N = 5


def log(msg):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def agent_answer(question: str, repo: str) -> str:
    """Run repo-coach ask and return the answer string."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "core.cli.main",
             "ask", question, "--repo", repo],
            capture_output=True, text=True, timeout=120,
            cwd=SCRIPTS + "/..",
        )
        out = r.stdout.strip()
        if not out and r.stderr:
            return f"[error: {r.stderr.strip()[:200]}]"
        return out or "[no output]"
    except subprocess.TimeoutExpired:
        return "[error: timeout]"
    except Exception as e:
        return f"[error: {e}]"


def haiku_answer(question: str) -> str:
    try:
        r = subprocess.run(
            ["claude", "-p", question,
             "--model", "claude-haiku-4-5-20251001",
             "--output-format", "json"],
            capture_output=True, text=True, timeout=120,
        )
        try:
            return json.loads(r.stdout)["result"].strip()
        except Exception:
            return r.stdout.strip()
    except Exception as e:
        return f"[error: {e}]"


def judge(question: str, reference: str, candidate: str) -> int:
    """Score 1-5 using Claude Sonnet as judge."""
    prompt = (
        "You are grading a coding assistant's answer.\n"
        f"QUESTION: {question}\n\n"
        f"REFERENCE (ideal) ANSWER: {reference}\n\n"
        f"CANDIDATE ANSWER: {candidate}\n\n"
        "Score the candidate 1-5 for correctness and usefulness vs the reference "
        "(5=as good or better, 1=wrong/useless). Reply with ONLY the integer."
    )
    try:
        r = subprocess.run(
            ["claude", "-p", prompt,
             "--model", "claude-sonnet-4-6",
             "--output-format", "json"],
            capture_output=True, text=True, timeout=120,
        )
        try:
            txt = json.loads(r.stdout)["result"]
        except Exception:
            txt = r.stdout
        for tok in txt.split():
            if tok.strip().isdigit():
                return max(1, min(5, int(tok.strip())))
    except Exception:
        pass
    return 0


def check_ollama() -> bool:
    try:
        r = subprocess.run(
            ["curl", "-sf", "http://localhost:11434/api/tags"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def avg(xs):
    xs = [x for x in xs if x > 0]
    return round(statistics.mean(xs), 2) if xs else 0.0


def main():
    parser = argparse.ArgumentParser(description="Benchmark repo-coach agent vs Haiku")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="Number of test questions")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Indexed repo path")
    args = parser.parse_args()

    if not os.path.exists(TEST):
        raise SystemExit(f"No test data at {TEST} — run 04_prepare_data.py first.")

    repo = os.path.expanduser(args.repo)
    index_dir = os.path.join(repo, ".repo-coach", "manifest.json")
    if not os.path.exists(index_dir):
        raise SystemExit(f"No index at {repo}/.repo-coach/ — run: repo-coach build {repo}")

    ollama_ok = check_ollama()
    if not ollama_ok:
        log("WARNING: Ollama not running — agent answers will be errors.")
        log("         Start with: ollama serve && ollama pull qwen2.5-coder:1.5b")

    items = [json.loads(l) for l in open(TEST) if l.strip()]
    items = items[:args.n]
    log(f"Benchmarking {len(items)} questions | repo={repo} | ollama={'UP' if ollama_ok else 'DOWN'}")
    open(LOG, "a").write("=" * 60 + "\n")

    scores_agent = []
    scores_haiku = []

    for i, it in enumerate(items, 1):
        q = it["messages"][0]["content"]
        ref = it["messages"][1]["content"]
        log(f"\nQ{i}/{len(items)}: {q[:80]}")

        log(f"  Q{i} → agent...")
        a_agent = agent_answer(q, repo)
        s_agent = judge(q, ref, a_agent) if ollama_ok and not a_agent.startswith("[error") else 0
        scores_agent.append(s_agent)
        log(f"  Q{i} → agent score: {s_agent}")

        log(f"  Q{i} → haiku...")
        a_haiku = haiku_answer(q)
        s_haiku = judge(q, ref, a_haiku)
        scores_haiku.append(s_haiku)
        log(f"  Q{i} → haiku score: {s_haiku}")

    ag = avg(scores_agent)
    hk = avg(scores_haiku)
    total = len(items)
    wins_vs_haiku = sum(1 for a, h in zip(scores_agent, scores_haiku) if a >= h)

    log("\n" + "=" * 60)
    log("RESULTS (avg score 1-5, higher is better)")
    log("=" * 60)
    log(f"  repo-coach agent   : {ag}   {'✅' if ag >= hk * 0.9 else '⚠️'} vs Haiku")
    log(f"  Claude Haiku       : {hk}")
    log("-" * 60)
    log(f"  Agent ≥ Haiku      : {wins_vs_haiku}/{total}")
    log("=" * 60)

    if not ollama_ok:
        verdict = "INCOMPLETE — Ollama was down. Start ollama + re-run."
    elif ag >= hk:
        verdict = "STRONG — agent beats or matches Haiku."
    elif ag >= hk * 0.9:
        verdict = "CLOSE — agent within 10% of Haiku. Good for offline/cheap use."
    elif ag > 2.0:
        verdict = "USEFUL — agent gives meaningful answers but Haiku leads."
    else:
        verdict = "NOT YET — agent answers too weak. Check Ollama model + index."

    log(f"VERDICT: {verdict}")

    record = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "n": total, "repo": repo,
        "agent": ag, "haiku": hk,
        "wins_vs_haiku": wins_vs_haiku,
        "ollama_ok": ollama_ok,
        "verdict": verdict,
    }
    with open(HISTORY, "a") as fh:
        fh.write(json.dumps(record) + "\n")
    log(f"Appended to {HISTORY}")


if __name__ == "__main__":
    main()
