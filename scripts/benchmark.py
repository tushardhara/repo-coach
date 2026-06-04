#!/usr/bin/env python3
"""
RepoCoach Benchmark — does the fine-tuned model actually beat the baselines?

Runs the held-out test.jsonl questions through:
  1. Base Qwen (no fine-tuning)        — did fine-tuning help at all?
  2. Your fine-tuned model             — the candidate
  3. Fine-tuned + graph RAG context    — hybrid (if graph.json exists)
  4. Claude Haiku (via claude -p)      — the bar to beat for the sub-agent plan

Each answer is scored 1–5 by an LLM judge (claude -p) against the reference
answer from the test set. Prints a comparison table + win-rate, appends to
benchmark_history.log so you can track improvement across retrains.

This is the instrument that decides whether fine-tuning is paying off.
"""
import os, json, subprocess, statistics, datetime, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graph_builder import query_graph

WS = os.path.expanduser("~/finetune-workspace")
os.chdir(WS)

TEST = "data/test.jsonl"
if not os.path.exists(TEST):
    raise SystemExit("No data/test.jsonl — run 04_prepare_data.py first.")

GRAPH_PATH = "graph.json"
graph = None
if os.path.exists(GRAPH_PATH):
    graph = json.load(open(GRAPH_PATH))
    print(f"Graph loaded: {graph['stats']['files']} files, {graph['stats']['functions']} fns")

items = [json.loads(l) for l in open(TEST) if l.strip()]
# cap for cost/time; held-out questions only
items = items[:15]
print(f"Benchmarking on {len(items)} held-out questions...\n")


def mlx_answer(model_path, prompt):
    try:
        r = subprocess.run(
            ["python3", "-m", "mlx_lm", "generate", "--model", model_path,
             "--max-tokens", "300", "--prompt", prompt],
            capture_output=True, text=True, timeout=180)
        return r.stdout.strip()
    except Exception as e:
        return f"[error: {e}]"


def haiku_answer(prompt):
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--model", "claude-haiku-4-5-20251001",
             "--output-format", "json"],
            capture_output=True, text=True, timeout=120)
        # claude -p --output-format json returns a JSON envelope with .result
        try:
            return json.loads(r.stdout)["result"].strip()
        except Exception:
            return r.stdout.strip()
    except Exception as e:
        return f"[error: {e}]"


def judge(question, reference, candidate):
    """Score candidate 1-5 vs reference using claude -p as judge."""
    prompt = (
        "You are grading a coding assistant's answer.\n"
        f"QUESTION: {question}\n\n"
        f"REFERENCE (ideal) ANSWER: {reference}\n\n"
        f"CANDIDATE ANSWER: {candidate}\n\n"
        "Score the candidate 1-5 for correctness and usefulness vs the reference "
        "(5=as good or better, 1=wrong/useless). Reply with ONLY the integer.")
    try:
        r = subprocess.run(["claude", "-p", prompt, "--output-format", "json"],
                           capture_output=True, text=True, timeout=120)
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


scores = {"base": [], "finetuned": [], "finetuned_graph": [], "haiku": []}
for i, it in enumerate(items, 1):
    q   = it["messages"][0]["content"]
    ref = it["messages"][1]["content"]
    print(f"[{i}/{len(items)}] {q[:60]}...")

    a_base = mlx_answer("./base-model", q)
    a_ft   = mlx_answer("./my-coder-model", q)
    a_hk   = haiku_answer(q)

    scores["base"].append(judge(q, ref, a_base))
    scores["finetuned"].append(judge(q, ref, a_ft))
    scores["haiku"].append(judge(q, ref, a_hk))

    if graph:
        ctx = query_graph(q, graph)
        q_with_ctx = f"{ctx}\n\n{q}" if ctx else q
        a_ft_graph = mlx_answer("./my-coder-model", q_with_ctx)
        scores["finetuned_graph"].append(judge(q, ref, a_ft_graph))
    else:
        scores["finetuned_graph"].append(0)


def avg(xs):
    xs = [x for x in xs if x > 0]
    return round(statistics.mean(xs), 2) if xs else 0.0

b, f, fg, h = (avg(scores["base"]), avg(scores["finetuned"]),
               avg(scores["finetuned_graph"]) if graph else None,
               avg(scores["haiku"]))
wins_vs_base  = sum(1 for x, y in zip(scores["finetuned"], scores["base"])  if x > y)
wins_vs_haiku = sum(1 for x, y in zip(scores["finetuned"], scores["haiku"]) if x >= y)
total = len(items)

print("\n" + "=" * 56)
print("RESULTS (avg score 1-5, higher is better)")
print("=" * 56)
print(f"  Base Qwen (no FT)    : {b}")
print(f"  Fine-tuned           : {f}   {'✅' if f > b else '⚠️'} vs base")
if graph and fg is not None:
    print(f"  Fine-tuned + graph   : {fg}  {'✅' if fg > f else '⚠️'} vs ft alone")
print(f"  Claude Haiku         : {h}")
print("-" * 56)
print(f"  Fine-tuned beats base  : {wins_vs_base}/{total}")
print(f"  Fine-tuned ≥ Haiku     : {wins_vs_haiku}/{total}")
print("=" * 56)

best_ft = fg if (graph and fg and fg > f) else f
if best_ft > b and best_ft >= h * 0.9:
    verdict = "STRONG — fine-tuning helps and is competitive with Haiku."
elif best_ft > b:
    verdict = "USEFUL — beats base, but Haiku still leads. Good for cheap/offline tasks."
else:
    verdict = "NOT YET — fine-tuning isn't beating base. Add data/diversity or reconsider."
print("VERDICT:", verdict)

with open("benchmark_history.log", "a") as log:
    log.write(json.dumps({
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "n": total, "base": b, "finetuned": f,
        "finetuned_graph": fg, "haiku": h,
        "wins_vs_base": wins_vs_base, "wins_vs_haiku": wins_vs_haiku,
        "verdict": verdict
    }) + "\n")
print("\nAppended to benchmark_history.log")
