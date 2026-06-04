def cmd_debug_context(question: str, repo: str):
    """
    Print the evidence/context that would be sent to Qwen for this question.
    Does NOT call Qwen. Shows:
    - Question classification (strategy)
    - First tool suggestion + result
    - Formatted evidence string
    """
    from core.navigator.graph_tools import GraphStore
    from core.navigator.planner import classify_question, suggest_first_tool
    from core.navigator.evidence_packer import (
        pack_flow_evidence,
        pack_impact_evidence,
        pack_table_evidence,
        pack_symbol_evidence,
    )
    import json, os

    repo = os.path.abspath(repo)
    graph = GraphStore(repo)
    if not graph.is_ready():
        print(f"No index at {repo}/.repo-coach/. Run: repo-coach build {repo}")
        raise SystemExit(1)

    strategy = classify_question(question)
    first_tool, first_args = suggest_first_tool(question, strategy)

    print("=" * 60)
    print(f"QUESTION: {question}")
    print(f"STRATEGY: {strategy}")
    print(f"FIRST TOOL: {first_tool}({json.dumps(first_args)})")
    print("=" * 60)

    result_json = graph.dispatch_tool(first_tool, first_args)
    result = json.loads(result_json)
    print(f"\nTOOL RESULT ({first_tool}):")
    print(json.dumps(result, indent=2)[:2000])

    print(f"\nEVIDENCE CONTEXT:")
    if strategy == "flow":
        evidence = _flow_evidence(graph, question, result, first_tool)
    elif strategy == "table":
        evidence = pack_table_evidence(question, result if isinstance(result, dict) else {"raw": result})
    elif strategy == "impact":
        evidence = _impact_evidence(graph, question, result)
    else:
        evidence = json.dumps(result, indent=2)[:1000]

    print(evidence)
    print(f"\n{'=' * 60}")
    print(f"Evidence length: {len(evidence)} chars")


_HANDLER_HINTS = ("handler", "Handler", "route", "Route", "controller", "Controller",
                  "endpoint", "Endpoint", "api", "Api", "API")


def _pick_handler(result: list, known_handler_ids: set = None) -> str:
    """Pick best symbol id from a find_symbols/find_routes result.

    Priority:
    1. Known route handler (appears in EXPOSES_ROUTE) and not setup/test
    2. Function/method with handler-like name, not setup/test
    3. Any function/method not setup/test
    """
    if not result:
        return ""
    known = known_handler_ids or set()

    # Tier 1: confirmed route handlers
    for item in result:
        sid = item.get("id", "")
        if sid in known and not _is_setup_handler(sid):
            return sid

    # Tier 2: function/method with route-handler naming hint
    for item in result:
        sid = item.get("id", "")
        kind = item.get("kind", "")
        name = item.get("name", "")
        if kind in ("function", "method") and not _is_setup_handler(sid):
            if any(h in name for h in _HANDLER_HINTS):
                return sid

    # Tier 3a: non-setup non-test function in a routes/handlers directory
    _ROUTE_DIRS = ("routes", "handlers", "controllers", "endpoints", "api")
    for item in result:
        sid = item.get("id", "")
        kind = item.get("kind", "")
        fpath = item.get("file", "").lower()
        if kind in ("function", "method") and not _is_setup_handler(sid):
            if any(d in fpath for d in _ROUTE_DIRS):
                return sid

    # Tier 3b: any non-setup non-test function/method
    for item in result:
        sid = item.get("id", "")
        kind = item.get("kind", "")
        if kind in ("function", "method") and not _is_setup_handler(sid):
            return sid

    return result[0].get("id") or result[0].get("handler_id", "")


_SETUP_NAMES = {"setup", "init", "main", "register", "routes", "router", "wire",
                "bootstrap", "configure", "mount", "install"}
_TEST_PREFIXES = ("test", "Test", "Benchmark", "benchmark")


def _is_setup_handler(handler_id: str) -> bool:
    """True if handler looks like a router-setup or test function, not a real handler."""
    if not handler_id:
        return True
    name_part = handler_id.split(":")[-1]
    if any(name_part.startswith(p) for p in _TEST_PREFIXES):
        return True
    return any(w in name_part.lower() for w in _SETUP_NAMES)


def _flow_evidence(graph, question, result, first_tool):
    import json
    from core.navigator.evidence_packer import pack_flow_evidence
    from core.navigator.planner import _extract_keywords

    handler_id = ""
    route_path = ""

    # Build set of known route handler IDs for priority picking
    known_handlers = {
        r.from_id for r in graph.relations if r.type == "EXPOSES_ROUTE"
    }

    # 1. If find_routes returned hits, use the handler_id from the route
    if first_tool == "find_routes" and isinstance(result, list) and result:
        for item in result:
            hid = item.get("handler_id", "")
            if hid and not _is_setup_handler(hid):
                handler_id = hid
                route_path = item.get("path", "")
                break
        if not handler_id:
            route_path = result[0].get("path", "") if result else ""

    # 2. If find_symbols returned hits, prefer real handler
    if not handler_id and isinstance(result, list):
        handler_id = _pick_handler(result, known_handlers)

    # 3. Fallback: try find_symbols with all meaningful keywords from question/route
    if not handler_id or _is_setup_handler(handler_id):
        from core.navigator.planner import _STEM_MAP, _STOPWORDS
        words = question.split()
        candidates = []
        for w in words:
            clean = w.strip("?.,!").lower()
            stemmed = _STEM_MAP.get(clean, clean)
            if stemmed and stemmed not in _STOPWORDS and len(stemmed) >= 3:
                candidates.append(stemmed)
        if route_path:
            for seg in route_path.strip("/").split("/"):
                seg = seg.replace("-", "").replace("_", "")
                if seg and not seg.startswith(":") and len(seg) >= 3:
                    candidates.append(seg)
        # Also try CamelCase compounds of the keywords (e.g. "assign"+"voucher" → "AssignVoucher")
        compounds = []
        base = [c for c in candidates if len(c) >= 4]
        for i, a in enumerate(base):
            for b in base[i+1:]:
                compounds.append(a.capitalize() + b.capitalize())
                compounds.append(b.capitalize() + a.capitalize())
        all_queries = list(dict.fromkeys(candidates + compounds))

        best_tier3b = ""
        _ROUTE_DIRS = ("routes", "handlers", "controllers", "endpoints", "api")
        for kw in all_queries:
            syms = json.loads(graph.dispatch_tool("find_symbols", {"query": kw}))
            candidate = _pick_handler(syms, known_handlers)
            if not candidate or _is_setup_handler(candidate):
                continue
            sym_info = next((s for s in syms if s.get("id") == candidate), {})
            fpath = sym_info.get("file", "").lower()
            is_route_dir = any(d in fpath for d in _ROUTE_DIRS)
            if is_route_dir or candidate in known_handlers:
                print(f"\n[debug-context] route handler via find_symbols({kw!r}): {candidate}")
                handler_id = candidate
                break
            if not best_tier3b:
                best_tier3b = candidate
        if not handler_id and best_tier3b:
            print(f"\n[debug-context] fallback handler: {best_tier3b}")
            handler_id = best_tier3b

    if not handler_id:
        return f"[No handler found for flow question]\nTool result: {json.dumps(result)[:500]}"

    print(f"\n[debug-context] building flow for: {handler_id}")
    flow = json.loads(graph.dispatch_tool("build_flow", {"entrypoint_id": handler_id}))
    if "error" in flow:
        return f"[Flow build failed: {flow['error']}]\nHandler: {handler_id}"
    return pack_flow_evidence(question, flow, {}, {})


def _impact_evidence(graph, question, result):
    import json
    from core.navigator.evidence_packer import pack_impact_evidence
    if isinstance(result, list) and result:
        first_id = result[0].get("id", "")
        impact = json.loads(graph.dispatch_tool("build_impact", {"symbol_id": first_id}))
        return pack_impact_evidence(question, impact)
    return str(result)
