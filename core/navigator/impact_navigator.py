"""Standalone impact analysis utility."""
from collections import deque
from typing import Dict, List

from core.graph.schema import Symbol, Relation


def analyze_impact(
    symbol_id: str,
    symbols: Dict[str, Symbol],
    caller_map: Dict[str, List[Relation]],
    relations: List[Relation],
    max_depth: int = 5,
) -> dict:
    """
    BFS backward from symbol_id following CALLS edges.
    Identify callers and affected routes via EXPOSES_ROUTE.
    """
    sym = symbols.get(symbol_id)
    if not sym:
        return {"error": f"symbol {symbol_id!r} not found"}

    # Build handler → route lookup from EXPOSES_ROUTE
    handler_to_route: Dict[str, str] = {}
    for rel in relations:
        if rel.type == "EXPOSES_ROUTE":
            handler_to_route[rel.from_id] = rel.to_id

    visited = {symbol_id}
    queue = deque([(symbol_id, 0)])
    direct_callers: List[dict] = []
    all_callers: List[dict] = []
    depth_reached = 0

    while queue:
        cur_id, depth = queue.popleft()
        if depth >= max_depth:
            depth_reached = max(depth_reached, depth)
            continue
        for rel in caller_map.get(cur_id, []):
            nxt = rel.from_id
            if nxt in visited:
                continue
            visited.add(nxt)
            caller_sym = symbols.get(nxt)
            if caller_sym is None:
                continue
            entry = {
                "id": caller_sym.id,
                "name": caller_sym.name,
                "file": caller_sym.file,
            }
            all_callers.append(entry)
            if depth == 0:
                direct_callers.append(entry)
            depth_reached = max(depth_reached, depth + 1)
            queue.append((nxt, depth + 1))

    # Affected routes
    affected_routes: List[dict] = []
    seen_routes: set = set()
    for entry in all_callers:
        handler_id = entry["id"]
        route_id = handler_to_route.get(handler_id)
        if route_id and route_id not in seen_routes:
            seen_routes.add(route_id)
            route_sym = symbols.get(route_id)
            affected_routes.append({
                "route_id": route_id,
                "route_name": route_sym.name if route_sym else route_id,
                "handler_id": handler_id,
            })

    return {
        "symbol": {"id": sym.id, "name": sym.name, "file": sym.file},
        "direct_callers": direct_callers,
        "all_callers": all_callers,
        "affected_routes": affected_routes,
        "depth_reached": depth_reached,
    }
