# Benchmarking — Is the model actually good?

`scripts/benchmark.py` produces an honest score by comparing three models on
the **held-out** `test.jsonl` (questions the model never trained on):

| Model | Why it's here |
|---|---|
| Base Qwen (no FT) | Did fine-tuning help *at all*? |
| Your fine-tuned model | The candidate |
| Claude Haiku | The bar to beat for the sub-agent plan |

Each answer is scored 1–5 by an LLM judge (`claude -p`) against the reference
answer. Output: average scores, win-rates, and a verdict.

```bash
python3 scripts/benchmark.py
```

## Reading the verdict
- **STRONG** — beats base AND competitive with Haiku → pursue the sub-agent plan.
- **USEFUL** — beats base but Haiku leads → good for cheap/offline/private tasks.
- **NOT YET** — doesn't beat base → add data + diversity, or use retrieval instead.

## Research context
- Small (1–1.5B) models show a clear size-performance tradeoff vs 7–8B (npj Digital Medicine 2025).
- 200–500 pairs is the practical minimum for behavior change; 1000+ for style shift (markaicode 2026).
- Low synthetic-data diversity causes model collapse — our agents are prompted for diversity (arXiv 2511.01490).
- LoRA + low LR (2e-5) acts as a regularizer that mitigates catastrophic forgetting (Dialzara 2025; arXiv 2411.11907).

Results append to `benchmark_history.log` so you can track improvement across retrains.
