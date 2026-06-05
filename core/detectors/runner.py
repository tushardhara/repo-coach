"""Orchestrate all detectors over all files in the repo."""
import os
from collections import defaultdict
from typing import Dict, List, Tuple

from core.graph.schema import Fact, FileRecord, Relation, Symbol
from core.detectors.routes import detect as detect_routes
from core.detectors.sql import detect as detect_sql
from core.detectors.redis import detect as detect_redis
from core.detectors.queues import detect as detect_queues
from core.detectors.events import detect as detect_events
from core.detectors.http import detect as detect_http


DETECTORS = [
    detect_routes,
    detect_sql,
    detect_redis,
    detect_queues,
    detect_events,
    detect_http,
]


def detect_all(
    repo_root: str,
    files: List[FileRecord],
    symbols: List[Symbol],
    contents: dict = None,
) -> Tuple[List[Fact], List[Relation]]:
    """
    Run all detectors over every file.
    Returns (facts, extra_relations).
    Facts are deduplicated by (owner, type, target).
    """
    # Build per-file symbol lookup
    file_symbol_map: Dict[str, List[Symbol]] = defaultdict(list)
    for sym in symbols:
        file_symbol_map[sym.file].append(sym)

    all_facts: List[Fact] = []
    all_relations: List[Relation] = []
    seen_facts: set = set()

    for file_record in files:
        abs_path = os.path.join(repo_root, file_record.path)
        rel_path = file_record.path
        file_symbols = file_symbol_map.get(rel_path, [])

        if contents is not None and rel_path in contents:
            content = contents[rel_path]
        else:
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except OSError as exc:
                print(f"[detectors] warning: cannot read {abs_path}: {exc}")
                continue

        for detector in DETECTORS:
            try:
                facts, relations = detector(abs_path, rel_path, content, file_symbols)
            except Exception as exc:  # noqa: BLE001
                print(f"[detectors] warning: {detector.__module__} failed on {rel_path}: {exc}")
                continue

            for fact in facts:
                key = (fact.owner, fact.type, fact.target)
                if key not in seen_facts:
                    seen_facts.add(key)
                    all_facts.append(fact)

            all_relations.extend(relations)

    return all_facts, all_relations
