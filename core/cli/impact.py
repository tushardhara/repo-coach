def cmd_impact(symbol: str, repo: str):
    """Show impact of a symbol change."""
    from core.navigator.graph_tools import GraphStore
    from core.navigator.evidence_packer import pack_impact_evidence
    import json
    import os

    repo = os.path.abspath(repo)
    graph = GraphStore(repo)
    if not graph.is_ready():
        print(f"No index. Run: repo-coach build {repo}")
        raise SystemExit(1)

    results = graph.find_symbols(symbol)
    if not results:
        print(f"Symbol not found: {symbol}")
        raise SystemExit(1)

    sym_id = results[0]["id"]
    print(f"Analyzing impact for: {sym_id}\n")
    impact = json.loads(graph.dispatch_tool("build_impact", {"symbol_id": sym_id}))
    print(pack_impact_evidence(symbol, impact))
