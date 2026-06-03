#!/usr/bin/env python3
import os, subprocess, sys
WS = os.path.expanduser("~/finetune-workspace")
os.chdir(WS)
# read BASE_MODEL from config
cfg = {}
here = os.path.dirname(os.path.abspath(__file__))
for line in open(os.path.join(here, "..", "configs", "config.env")):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        cfg[k] = v.strip().strip('"')
model = cfg.get("BASE_MODEL", "Qwen/Qwen2.5-Coder-1.5B-Instruct")
from huggingface_hub import snapshot_download
print(f"Downloading {model}...")
snapshot_download(repo_id=model, local_dir="./base-model", ignore_patterns=["*.bin"])
print("✅ Base model ready")
