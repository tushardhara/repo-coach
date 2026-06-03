#!/bin/bash
set -e
echo "════ INSTALL ════"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
python3 -m venv ~/finetune-env
source ~/finetune-env/bin/activate
pip install --upgrade pip
pip install -r "$HERE/requirements.txt"
python3 -c "import mlx.core as mx; import mlx_lm; print('✅ MLX', mx.__version__, '| mlx_lm OK |', mx.default_device())"
