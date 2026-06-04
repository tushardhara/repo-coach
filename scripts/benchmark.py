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

LOG = os.path.join(WS, "benchmark_progress.log")

def log(msg):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

TEST = "data/test.jsonl"
if not os.path.exists(TEST):
    raise SystemExit("No data/test.jsonl — run 04_prepare_data.py first.")

GRAPH_PATH = "graph.json"
graph = None
if os.path.exists(GRAPH_PATH):
    graph = json.load(open(GRAPH_PATH))
    log(f"Graph loaded: {graph['stats']['files']} files, {graph['stats']['functions']} fns")

items = [json.loads(l) for l in open(TEST) if l.strip()]
items = items[:5]
log(f"Starting benchmark on {len(items)} held-out questions...")
open(LOG, "a").write("=" * 56 + "\n")


def mlx_answer(model_path, prompt):
    # Apply Qwen2.5-Instruct chat template — without it, instruct models ignore the prompt
    formatted = (
        f"<|im_start|>system\nYou are a helpful coding assistant.<|im_end|>\n"
        f"<|im_start|>user\n{prompt}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )
    try:
        r = subprocess.run(
            ["python3", "-m", "mlx_lm", "generate", "--model", model_path,
             "--max-tokens", "300", "--repetition-penalty", "1.1", "--prompt", formatted],
            capture_output=True, text=True, timeout=180)
        # Strip everything up to and including the prompt echo if present
        out = r.stdout.strip()
        if "<|im_start|>assistant" in out:
            out = out.split("<|im_start|>assistant")[-1].strip()
        return out
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
        # Pin judge to Sonnet — never Haiku, which would score itself higher
        r = subprocess.run(["claude", "-p", prompt,
                            "--model", "claude-sonnet-4-6",
                            "--output-format", "json"],
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


def log_answer(label, answer):
    sep = "-" * 40
    with open(LOG, "a") as f:
        f.write(f"\n  [{label}]\n{sep}\n{answer[:500]}\n{sep}\n")

scores = {"base": [], "finetuned": [], "finetuned_graph": [], "haiku": []}
for i, it in enumerate(items, 1):
    q   = it["messages"][0]["content"]
    ref = it["messages"][1]["content"]
    log(f"\nQ{i}/{len(items)}: {q}")
    log_answer("REFERENCE", ref)

    log(f"  Q{i} → base model inference...")
    a_base = mlx_answer("./base-model", q)
    log_answer("BASE", a_base)
    s_base = judge(q, ref, a_base)
    scores["base"].append(s_base)
    log(f"  Q{i} → base score: {s_base}")

    log(f"  Q{i} → fine-tuned model inference...")
    a_ft = mlx_answer("./my-coder-model", q)
    log_answer("FINE-TUNED", a_ft)
    s_ft = judge(q, ref, a_ft)
    scores["finetuned"].append(s_ft)
    log(f"  Q{i} → finetuned score: {s_ft}")

    log(f"  Q{i} → Haiku inference...")
    a_hk = haiku_answer(q)
    log_answer("HAIKU", a_hk)
    s_hk = judge(q, ref, a_hk)
    scores["haiku"].append(s_hk)
    log(f"  Q{i} → haiku score: {s_hk}")

    if graph:
        log(f"  Q{i} → fine-tuned+graph inference...")
        ctx = query_graph(q, graph)
        q_with_ctx = f"{ctx}\n\n{q}" if ctx else q
        a_ft_graph = mlx_answer("./my-coder-model", q_with_ctx)
        log_answer("FINE-TUNED+GRAPH", a_ft_graph)
        s_ftg = judge(q, ref, a_ft_graph)
        scores["finetuned_graph"].append(s_ftg)
        log(f"  Q{i} → finetuned+graph score: {s_ftg}")
    else:
        scores["finetuned_graph"].append(0)

    log(f"Q{i} done → base={s_base} ft={s_ft} haiku={s_hk}")


def avg(xs):
    xs = [x for x in xs if x > 0]
    return round(statistics.mean(xs), 2) if xs else 0.0

b, f, fg, h = (avg(scores["base"]), avg(scores["finetuned"]),
               avg(scores["finetuned_graph"]) if graph else None,
               avg(scores["haiku"]))
wins_vs_base  = sum(1 for x, y in zip(scores["finetuned"], scores["base"])  if x > y)
wins_vs_haiku = sum(1 for x, y in zip(scores["finetuned"], scores["haiku"]) if x >= y)
total = len(items)

log("\n" + "=" * 56)
log("RESULTS (avg score 1-5, higher is better)")
log("=" * 56)
log(f"  Base Qwen (no FT)    : {b}")
log(f"  Fine-tuned           : {f}   {'✅' if f > b else '⚠️'} vs base")
if graph and fg is not None:
    log(f"  Fine-tuned + graph   : {fg}  {'✅' if fg > f else '⚠️'} vs ft alone")
log(f"  Claude Haiku         : {h}")
log("-" * 56)
log(f"  Fine-tuned beats base  : {wins_vs_base}/{total}")
log(f"  Fine-tuned ≥ Haiku     : {wins_vs_haiku}/{total}")
log("=" * 56)

best_ft = fg if (graph and fg and fg > f) else f
if best_ft > b and best_ft >= h * 0.9:
    verdict = "STRONG — fine-tuning helps and is competitive with Haiku."
elif best_ft > b:
    verdict = "USEFUL — beats base, but Haiku still leads. Good for cheap/offline tasks."
else:
    verdict = "NOT YET — fine-tuning isn't beating base. Add data/diversity or reconsider."
log(f"VERDICT: {verdict}")

with open("benchmark_history.log", "a") as fh:
    fh.write(json.dumps({
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "n": total, "base": b, "finetuned": f,
        "finetuned_graph": fg, "haiku": h,
        "wins_vs_base": wins_vs_base, "wins_vs_haiku": wins_vs_haiku,
        "verdict": verdict
    }) + "\n")
log("Appended to benchmark_history.log")
