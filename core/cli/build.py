def cmd_build(repo_path: str, verbose: bool = True):
    from core.index.builder import build
    import os

    repo_path = os.path.abspath(repo_path)
    if not os.path.isdir(repo_path):
        print(f"Error: not a directory: {repo_path}")
        raise SystemExit(1)
    stats = build(repo_path, verbose=verbose)
    print(f"\nBuild complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
