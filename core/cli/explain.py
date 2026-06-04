def cmd_explain(route: str, repo: str):
    """Explain a route's full flow using pre-built graph (no LLM)."""
    from core.navigator.graph_tools import GraphStore
    from core.navigator.evidence_packer import pack_flow_evidence
    import json
    import os

    repo = os.path.abspath(repo)
    graph = GraphStore(repo)
    if not graph.is_ready():
        print(f"No index. Run: repo-coach build {repo}")
        raise SystemExit(1)

    # Try to find route
    routes = graph.find_routes(route)
    if not routes:
        print(f"No route matching: {route}")
        print("Hint: try 'repo-coach build' first, or check route with 'repo-coach ask'")
        raise SystemExit(1)

    route_info = routes[0]
    handler_id = route_info.get("handler_id") or route_info.get("id")
    flow = json.loads(graph.dispatch_tool("build_flow", {"entrypoint_id": handler_id}))
    evidence = pack_flow_evidence(route, flow, {}, {})
    print(evidence)
