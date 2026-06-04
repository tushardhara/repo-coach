"""Write and read the file_index.jsonl artifact."""
import json
from typing import List

from core.graph.schema import FileRecord, write_jsonl, read_jsonl


def write_file_index(path: str, records: List[FileRecord]) -> int:
    return write_jsonl(path, records)


def load_file_index(path: str) -> List[FileRecord]:
    rows = read_jsonl(path)
    return [
        FileRecord(
            path=r["path"],
            language=r["language"],
            sha256=r["sha256"],
            lines=r["lines"],
            is_test=r["is_test"],
            id=r.get("id", f"file:{r['path']}"),
        )
        for r in rows
    ]
