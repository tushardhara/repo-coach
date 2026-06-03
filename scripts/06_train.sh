#!/bin/bash
set -e
echo "════ TRAIN ════"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source ~/finetune-env/bin/activate
cd ~/finetune-workspace
source train_params.env

# Build a runtime config from the template, injecting auto-sized values
python3 - "$HERE/configs/lora_config.yaml" "$ITERS" "$LAYERS" << 'PYEOF'
import sys, re
tmpl, iters, layers = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = open(tmpl).read()
cfg = re.sub(r'num_layers:.*', f'num_layers: {layers}', cfg, count=1)
cfg += f"\niters: {iters}\n"
cfg += "model: ./base-model\n"
cfg += "data: ./data\n"
cfg += "adapter_path: ./adapters\n"
cfg += "train: true\n"
open("runtime_lora.yaml","w").write(cfg)
print("Wrote runtime_lora.yaml (iters=%s layers=%s)" % (iters, layers))
PYEOF

echo "Starting fine-tune via YAML config..."
mlx_lm.lora --config runtime_lora.yaml
