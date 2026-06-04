"""Write and read symbols.jsonl."""
import json
from typing import List

from core.graph.schema import Symbol, write_jsonl, read_jsonl


def write_symbol_index(path: str, symbols: List[Symbol]) -> int:
    return write_jsonl(path, symbols)


def load_symbol_index(path: str) -> List[Symbol]:
    rows = read_jsonl(path)
    return [
        Symbol(
            id=r["id"],
            kind=r["kind"],
            name=r["name"],
            file=r["file"],
            start_line=r["start_line"],
            end_line=r["end_line"],
            signature=r.get("signature", ""),
            summary=r.get("summary", ""),
            package=r.get("package", ""),
            receiver=r.get("receiver", ""),
            language=r.get("language", ""),
        )
        for r in rows
    ]
