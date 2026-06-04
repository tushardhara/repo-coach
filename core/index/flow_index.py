"""Write and read flows.jsonl."""
from typing import List

from core.graph.schema import Flow, write_jsonl, read_jsonl


def write_flow_index(path: str, flows: List[Flow]) -> int:
    return write_jsonl(path, flows)


def load_flow_index(path: str) -> List[Flow]:
    rows = read_jsonl(path)
    out = []
    for r in rows:
        out.append(Flow(
            id=r["id"],
            entrypoint=r["entrypoint"],
            route=r.get("route", ""),
            chain=r.get("chain", []),
            db_reads=r.get("db_reads", []),
            db_writes=r.get("db_writes", []),
            redis=r.get("redis", []),
            queues=r.get("queues", []),
            events=r.get("events", []),
            http_calls=r.get("http_calls", []),
            unresolved=r.get("unresolved", []),
            confidence=r.get("confidence", 1.0),
            evidence=r.get("evidence", []),
        ))
    return out
