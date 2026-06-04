#!/usr/bin/env python3
"""
04_prepare_data.py — merge pairs, build graph, augment, split, auto-size.

Order:
  1. Load raw JSONL pairs from agents/
  2. Build graph.json from target repo (structure extraction, fast)
     — if graph.json already has LLM summaries (--enrich was run), reuses them
  3. 80/10/10 split → train / valid / test
  4. Graph-augment training set: duplicate each pair with graph context prepended
     (val/test stay clean — never see graph context during evaluation)
  5. Write data/{train,valid,test}.jsonl + train_params.env
"""
import json, glob, random, os, sys

WS          = os.path.expanduser("~/finetune-workspace")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPH_PATH  = os.path.join(WS, "graph.json")

os.chdir(WS)
sys.path.insert(0, SCRIPTS_DIR)
from graph_builder import build_graph, query_graph

# ── Step 1: Load raw pairs ────────────────────────────────────────────────────

pairs, seen = [], set()
for path in glob.glob("agents/dataset_*.jsonl"):
    for line in open(path, errors="ignore"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            assert rec["messages"][0]["role"] == "user"
            assert rec["messages"][1]["role"] == "assistant"
            key = rec["messages"][0]["content"][:80]
            if key not in seen:
                seen.add(key)
                pairs.append(rec)
        except Exception:
            pass

n = len(pairs)
print(f"Unique valid pairs: {n}")
if n < 50:
    print("WARNING: <50 pairs — heavy overfit risk. Raise PAIRS_PER_FILE.")
elif n < 200:
    print("NOTE: 50-200 pairs. 200-500 is practical minimum for real behavior change.")
elif n < 1000:
    print("OK: 200-1000 pairs — good range for behavior/style adaptation.")
else:
    print("Strong: 1000+ pairs — meaningful domain shift possible.")

# ── Step 2: Build graph ───────────────────────────────────────────────────────
# Repo root: use existing graph.json['repo'] if present, else ~/Promotions default

graph = None
repo_root = ''

existing_repo     = ''
existing_enriched = False
if os.path.exists(GRAPH_PATH):
    try:
        _existing = json.load(open(GRAPH_PATH))
        existing_repo     = _existing.get('repo', '')
        existing_enriched = _existing['stats'].get('enriched', False)
    except Exception:
        pass

candidate = existing_repo or os.path.expanduser('~/Promotions')

if existing_enriched:
    # Enriched graph (LLM summaries) — never overwrite, rebuild would lose summaries
    graph     = json.load(open(GRAPH_PATH))
    repo_root = graph.get('repo', '')
    s         = graph['stats']
    print(f"\nReusing enriched graph ({s['files']} files, {s['functions']} fns) — LLM summaries preserved")
    print("  To rebuild without summaries: delete graph.json first")
elif os.path.isdir(candidate):
    repo_root = candidate
    print(f"\nBuilding graph from {repo_root} ...")
    graph = build_graph(repo_root)
    json.dump(graph, open(GRAPH_PATH, 'w'), indent=2)
    s = graph['stats']
    print(f"Graph: {s['files']} files · {s['functions']} fns · {s['classes']} classes")
    print("  (run graph_builder.py --enrich to add LLM summaries for richer context)")
elif os.path.exists(GRAPH_PATH):
    graph     = json.load(open(GRAPH_PATH))
    repo_root = graph.get('repo', '')
    s         = graph['stats']
    print(f"Repo not found at {candidate} — using cached graph ({s['files']} files)")
else:
    print("No repo and no cached graph — skipping graph augmentation")

# ── Step 3: Split ────────────────────────────────────────────────────────────

random.shuffle(pairs)
n_test = max(1, int(n * 0.10))
n_val  = max(1, int(n * 0.10))
test  = pairs[:n_test]
valid = pairs[n_test:n_test + n_val]
train = pairs[n_test + n_val:] or pairs[:1]

os.makedirs("data", exist_ok=True)

# ── Step 4: Graph-augment training set ───────────────────────────────────────
# Each training pair that has matching graph context gets a duplicate with
# the context prepended. Val/test sets are NEVER augmented.

graph_train = []
if graph:
    n_aug = 0
    for rec in train:
        q   = rec["messages"][0]["content"]
        ctx = query_graph(q, graph, repo_root=repo_root)
        if ctx:
            aug = json.loads(json.dumps(rec))   # deep copy
            aug["messages"][0]["content"] = ctx + "\n\n" + q
            graph_train.append(aug)
            n_aug += 1
    print(f"Graph augmentation: +{n_aug} pairs added to train set")

train_final = train + graph_train
random.shuffle(train_final)

# ── Step 5: Write splits + auto-size params ───────────────────────────────────

for name, rows in [("train", train_final), ("valid", valid), ("test", test)]:
    with open(f"data/{name}.jsonl", "w") as f:
        for d in rows:
            f.write(json.dumps(d) + "\n")

# Target ~4 epochs at batch_size=2 (1 epoch = train_size / 2 iters). Cap at 3200.
iters  = min(max(len(train_final) * 2, 100), 3200)
layers = 4 if n < 100 else 8
with open("train_params.env", "w") as f:
    f.write(f"ITERS={iters}\nLAYERS={layers}\n")

print(f"\nTrain: {len(train_final)} (+{len(graph_train)} graph-aug) | "
      f"Valid: {len(valid)} | Test(held-out): {len(test)}")
print(f"Auto params → iters={iters}, layers={layers}")
