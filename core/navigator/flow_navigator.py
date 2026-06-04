"""Build Flow objects from symbols/relations/facts at index build time."""
from collections import deque
from dataclasses import field
from typing import Dict, List

from core.graph.schema import Symbol, Relation, Fact, Flow

_FACT_CATEGORIES = {
    "READS_TABLE": "db_reads",
    "WRITES_TABLE": "db_writes",
    "USES_REDIS": "redis",
    "PUBLISHES_QUEUE": "queues",
    "CONSUMES_QUEUE": "queues",
    "PUBLISHES_EVENT": "events",
    "CALLS_HTTP": "http_calls",
}


def _dedup(lst: list) -> list:
    return list(dict.fromkeys(lst))


def build_all_flows(
    symbols: List[Symbol],
    relations: List[Relation],
    facts: List[Fact],
) -> List[Flow]:
    """
    Find all route handlers (from_id in EXPOSES_ROUTE relations).
    BFS-walk CALLS edges per handler (max depth 8, max 30 nodes).
    Collect side-effects from facts.
    Return list of Flow objects.
    """
    # Build in-memory maps
    sym_map: Dict[str, Symbol] = {s.id: s for s in symbols}
    callee_map: Dict[str, List[str]] = {}   # from_id → [to_id, ...]
    fact_map: Dict[str, List[Fact]] = {}    # owner → facts

    for rel in relations:
        if rel.type == "CALLS":
            callee_map.setdefault(rel.from_id, []).append(rel.to_id)

    for fact in facts:
        fact_map.setdefault(fact.owner, []).append(fact)

    # Collect handler → route pairs from EXPOSES_ROUTE
    handler_route_pairs: List[tuple] = []  # (handler_id, route_id)
    for rel in relations:
        if rel.type == "EXPOSES_ROUTE":
            handler_route_pairs.append((rel.from_id, rel.to_id))

    flows: List[Flow] = []

    for handler_id, route_id in handler_route_pairs:
        if handler_id not in sym_map:
            continue

        route_sym = sym_map.get(route_id)
        route_str = route_sym.name if route_sym else ""

        # BFS from handler
        chain: List[str] = []
        visited = {handler_id}
        queue = deque([(handler_id, 0)])
        db_reads, db_writes, redis_keys = [], [], []
        queues, events, http_calls, evidence = [], [], [], []

        while queue:
            cur_id, depth = queue.popleft()
            chain.append(cur_id)

            for f in fact_map.get(cur_id, []):
                cat = _FACT_CATEGORIES.get(f.type)
                if cat == "db_reads":
                    db_reads.append(f.target)
                elif cat == "db_writes":
                    db_writes.append(f.target)
                elif cat == "redis":
                    redis_keys.append(f.target)
                elif cat == "queues":
                    queues.append(f.target)
                elif cat == "events":
                    events.append(f.target)
                elif cat == "http_calls":
                    http_calls.append(f.target)
                if f.evidence:
                    evidence.append(f.evidence)

            if depth >= 8 or len(chain) >= 30:
                continue

            for nxt_id in callee_map.get(cur_id, []):
                if nxt_id not in visited and nxt_id in sym_map:
                    visited.add(nxt_id)
                    queue.append((nxt_id, depth + 1))

        flow_id = f"flow:{route_str or handler_id}"
        flow = Flow(
            id=flow_id,
            entrypoint=handler_id,
            route=route_str,
            chain=chain,
            db_reads=_dedup(db_reads),
            db_writes=_dedup(db_writes),
            redis=_dedup(redis_keys),
            queues=_dedup(queues),
            events=_dedup(events),
            http_calls=_dedup(http_calls),
            unresolved=[],
            confidence=1.0,
            evidence=evidence,
        )
        flows.append(flow)

    return flows
