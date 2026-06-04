#!/usr/bin/env python3
"""Merge, dedupe, 3-way split (train/valid/test), auto-size, warn on small data.
Graph augmentation: when graph.json exists, adds graph-context copies of training pairs."""
import json, glob, random, os, sys

WS = os.path.expanduser("~/finetune-workspace")
os.chdir(WS)

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

# Research-backed size guidance (markaicode 2026; dialzara 2025)
if n < 50:
    print("🔴 WARNING: <50 pairs. Will train but heavily overfit. Raise PAIRS_PER_FILE and rerun.")
elif n < 200:
    print("🟡 NOTE: 50–200 pairs. Trains, but 200–500 is the practical minimum for real behavior change.")
elif n < 1000:
    print("🟢 OK: 200–1000 pairs — good range for behavior/style adaptation.")
else:
    print("🟢 Strong: 1000+ pairs — meaningful style/domain shift possible.")

random.shuffle(pairs)
# 80/10/10 split → train / valid / test  (test is HELD OUT for benchmark.py)
n_test = max(1, int(n * 0.10))
n_val  = max(1, int(n * 0.10))
test  = pairs[:n_test]
valid = pairs[n_test:n_test + n_val]
train = pairs[n_test + n_val:] or pairs[:1]

os.makedirs("data", exist_ok=True)

# Graph augmentation — inject graph context into training pairs only (val/test stay clean)
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPH_PATH  = os.path.join(WS, "graph.json")
graph_train = []
if os.path.exists(GRAPH_PATH):
    try:
        sys.path.insert(0, SCRIPTS_DIR)
        from graph_builder import query_graph
        graph = json.load(open(GRAPH_PATH))
        n_aug = 0
        for rec in train:
            q   = rec["messages"][0]["content"]
            ctx = query_graph(q, graph)
            if ctx:
                aug = json.loads(json.dumps(rec))          # deep copy
                aug["messages"][0]["content"] = ctx + "\n\n" + q
                graph_train.append(aug)
                n_aug += 1
        print(f"Graph: {graph['stats']['files']} files, {graph['stats']['functions']} fns → "
              f"+{n_aug} augmented pairs added to train")
    except Exception as e:
        print(f"Graph augmentation skipped: {e}")

train_final = train + graph_train
random.shuffle(train_final)

for name, rows in [("train", train_final), ("valid", valid), ("test", test)]:
    with open(f"data/{name}.jsonl", "w") as f:
        for d in rows:
            f.write(json.dumps(d) + "\n")

# Auto-size iters (≈4 passes, clamped) and layers — based on augmented train size
iters  = min(max(len(train_final) * 4, 100), 800)
layers = 4 if n < 100 else 8
with open("train_params.env", "w") as f:
    f.write(f"ITERS={iters}\nLAYERS={layers}\n")

print(f"Train: {len(train_final)} (+{len(graph_train)} graph-aug) | Valid: {len(valid)} | Test(held-out): {len(test)}")
print(f"Auto params → iters={iters}, layers={layers}")
