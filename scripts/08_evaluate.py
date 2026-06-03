#!/usr/bin/env python3
import os, json, subprocess
WS = os.path.expanduser("~/finetune-workspace")
os.chdir(WS)
here = os.path.dirname(os.path.abspath(__file__))
cfg = {}
for line in open(os.path.join(here, "..", "configs", "config.env")):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1); cfg[k] = v.strip().strip('"')
repo = os.path.basename(cfg["REPO_URL"]).replace(".git", "")
subprocess.run(["claude","-p",
  f"Read the repo at ~/{repo} and write 5 specific questions a dev would ask about THIS codebase. "
  f"Use Write tool to save 'eval_q.json' as {{\"questions\":[\"q1\"]}}. Reply 'done'.",
  "--allowedTools","Read,Glob,Grep,Write","--output-format","json"], stdout=subprocess.DEVNULL)
try:
    qs = json.load(open("eval_q.json"))["questions"]
except Exception:
    qs = ["What does this project do?", "How is the code organized?"]
for i, q in enumerate(qs, 1):
    r = subprocess.run(["python3","-m","mlx_lm.generate","--model","./my-coder-model",
        "--max-tokens","250","--prompt",q], capture_output=True, text=True)
    print(f"\nQ{i}: {q}\nA: {r.stdout.strip()[:300]}\n" + "-"*50)
