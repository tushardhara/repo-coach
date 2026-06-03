#!/bin/bash
set -e
echo "════ FUSE ════"
source ~/finetune-env/bin/activate
cd ~/finetune-workspace
mlx_lm.fuse --model ./base-model --adapter-path ./adapters --save-path ./my-coder-model
echo "✅ Model at ./my-coder-model"
