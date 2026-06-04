#!/bin/bash
set -e
echo "════ TRAIN ════"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source ~/finetune-env/bin/activate
cd ~/finetune-workspace
source train_params.env

# Build a runtime config from the template, injecting auto-sized values
python3 - "$HERE/configs/lora_config.yaml" "$ITERS" "$LAYERS" << 'PYEOF'
import sys, re, subprocess
tmpl, iters, layers = sys.argv[1], sys.argv[2], sys.argv[3]

# Auto batch_size: leave ~40% headroom for OS/GPU/other apps
mem_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
ram_gb = mem_bytes / (1024 ** 3)
if ram_gb >= 32:   batch = 8
elif ram_gb >= 24: batch = 4
elif ram_gb >= 16: batch = 2
else:              batch = 1
print(f"RAM: {ram_gb:.0f}GB → batch_size={batch}")

cfg = open(tmpl).read()
cfg = re.sub(r'num_layers:.*', f'num_layers: {layers}', cfg, count=1)
cfg = re.sub(r'batch_size:.*', f'batch_size: {batch}', cfg, count=1)
cfg += f"\niters: {iters}\n"
cfg += "model: ./base-model\n"
cfg += "data: ./data\n"
cfg += "adapter_path: ./adapters\n"
cfg += "train: true\n"
open("runtime_lora.yaml","w").write(cfg)
print("Wrote runtime_lora.yaml (iters=%s layers=%s batch=%s)" % (iters, layers, batch))
PYEOF

echo "Starting fine-tune via YAML config..."
mlx_lm.lora --config runtime_lora.yaml
