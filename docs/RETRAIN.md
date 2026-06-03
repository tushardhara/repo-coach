# Retraining Strategy

## TL;DR
Don't retrain on every commit. Retrain when *patterns* change, and let
retrieval (`@codebase`) handle day-to-day freshness.

## Why not every commit?
- A full retrain costs ~40–60 min to absorb a few changed lines.
- Repeated tiny fine-tunes cause **catastrophic forgetting** in small models.
- Most commits change behavior, not the *conventions* fine-tuning captures.

## How RepoCoach handles it
`scripts/retrain.sh` is **change-aware** and **forgetting-safe**:

1. Compares current HEAD to the last-trained commit.
2. Counts changed *code* files.
3. Only retrains if `>= RETRAIN_MIN_CHANGED_FILES` changed (default 10).
4. Always retrains **from the base model on the full current dataset** —
   never incremental deltas — so the model can't drift or forget.

```bash
./scripts/retrain.sh           # checks threshold, retrains if warranted
./scripts/retrain.sh --force   # retrain now regardless
```

## Trigger options

### A) Git hook (recommended)
Runs a retrain *check* after merges into `main`:
```bash
./scripts/install_hook.sh
```

### B) Weekly cron
```bash
./scripts/setup_cron.sh
```

### C) Manual / CI
Call `retrain.sh` from your CI after release tags or big merges.

## Tuning the threshold
| Repo activity | Suggested `RETRAIN_MIN_CHANGED_FILES` |
|---|---|
| Very active (many daily commits) | 25–50 |
| Moderate | 10 (default) |
| Slow / stable | 5 |

## Freshness without retraining
Continue.dev's `@codebase` re-indexes your repo continuously. New code is
available to the assistant *immediately* via retrieval — no training needed.
Retraining is only for teaching new *style/conventions*.
