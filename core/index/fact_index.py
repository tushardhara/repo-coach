"""Write and read facts.jsonl."""
from typing import List

from core.graph.schema import Fact, write_jsonl, read_jsonl


def write_fact_index(path: str, facts: List[Fact]) -> int:
    return write_jsonl(path, facts)


def load_fact_index(path: str) -> List[Fact]:
    rows = read_jsonl(path)
    return [
        Fact(
            owner=r["owner"],
            type=r["type"],
            target=r["target"],
            evidence=r.get("evidence", ""),
            line=r.get("line", 0),
        )
        for r in rows
    ]
