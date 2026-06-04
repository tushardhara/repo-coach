"""Write and read relations.jsonl."""
from typing import List

from core.graph.schema import Relation, write_jsonl, read_jsonl


def write_relation_index(path: str, relations: List[Relation]) -> int:
    return write_jsonl(path, relations)


def load_relation_index(path: str) -> List[Relation]:
    rows = read_jsonl(path)
    return [
        Relation(
            from_id=r.get("from_id", r.get("from", "")),
            to_id=r.get("to_id", r.get("to", "")),
            type=r["type"],
            confidence=r.get("confidence", 1.0),
            evidence=r.get("evidence", ""),
            line=r.get("line", 0),
        )
        for r in rows
    ]
