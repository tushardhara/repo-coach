# Contributing to RepoCoach

Thanks for your interest! 🦴

## Ways to help
- **New base models**: add support for DeepSeek-Coder, CodeLlama, etc.
- **CUDA path**: a Linux/Windows variant using Unsloth instead of MLX
- **Tests**: a tiny sample repo + expected dataset shape
- **Docs**: clarify steps, fix typos

## Dev setup
1. Fork & clone
2. Make changes in `scripts/`
3. Test against a small public repo
4. Open a PR describing what changed and why

## Style
- Keep each script single-purpose and idempotent
- Every `claude -p` call MUST include `--allowedTools` (or it hangs)
- Prefer auto-detection over hardcoded values
