def cmd_table(table_name: str, repo: str):
    """Show DB table readers and writers."""
    from core.navigator.graph_tools import GraphStore
    from core.navigator.evidence_packer import pack_table_evidence
    import json
    import os

    repo = os.path.abspath(repo)
    graph = GraphStore(repo)
    if not graph.is_ready():
        print(f"No index. Run: repo-coach build {repo}")
        raise SystemExit(1)

    result = json.loads(graph.dispatch_tool("search_table", {"table_name": table_name}))
    print(pack_table_evidence(table_name, result))
