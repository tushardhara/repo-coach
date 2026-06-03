#!/bin/bash
set -e
echo "════ EXPORT TO OLLAMA ════"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/configs/config.env"
source ~/finetune-env/bin/activate
cd ~/finetune-workspace
pip install 'mlx-lm[gguf]' >/dev/null 2>&1 || true
mlx_lm.convert --hf-path ./my-coder-model --mlx-path ./my-coder-gguf -q --q-bits "$QUANT_BITS"
REPO_NAME=$(basename "$REPO_URL" .git)
GGUF=$(find ./my-coder-gguf -name "*.gguf" | head -1)
SYS="You are a coding assistant fine-tuned on the $REPO_NAME codebase."
[ "$CAVEMAN_MODE" = "true" ] && SYS="You are caveman coder for $REPO_NAME. Explain in caveman speak. Code stay correct. Ugh."
cat > Modelfile << MEOF
FROM $GGUF
SYSTEM "$SYS"
MEOF
(ollama serve >/dev/null 2>&1 &) ; sleep 3
ollama create "${REPO_NAME}-coder" -f ./Modelfile
echo "✅ ollama run ${REPO_NAME}-coder"
