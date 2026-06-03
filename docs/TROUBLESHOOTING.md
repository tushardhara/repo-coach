# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Agent hangs forever | Missing tool permissions | Ensure `--allowedTools` on the `claude -p` call |
| Empty `dataset_N.jsonl` | Agent errored | Read `agents/dataset_N.jsonl.log` |
| `MLX out of memory` | Batch too large | Add `--batch-size 2` in `06_train.sh` |
| Val loss spikes up | Overfitting | Halve `ITERS` in `train_params.env`, rerun phase 6 |
| `ollama: command not found` | Not installed | `brew install ollama` |
| Few pairs (<20) | Small repo / low PPF | Raise `PAIRS_PER_FILE`, rerun phases 3–4 |
| Caveman bleeds into code | Prompt ambiguity | Confirm `CAVEMAN_MODE` instruction keeps code clean |
| `claude -p` quota errors | Agent SDK credit pool | Check subscription usage limits |

## Resetting
```bash
rm -rf ~/finetune-workspace
./scripts/run.sh
```
