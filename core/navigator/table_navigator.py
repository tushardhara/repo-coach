"""Table access lookup utility."""
from typing import Dict, List

from core.graph.schema import Fact, Symbol

_TABLE_FACT_TYPES = {"READS_TABLE", "WRITES_TABLE"}


def search_table(
    table_name: str,
    facts: List[Fact],
    symbols: Dict[str, Symbol],
) -> dict:
    """
    Find facts where type in {READS_TABLE, WRITES_TABLE} and target contains table_name.
    Group into readers/writers.
    Each entry: {owner_id, owner_name, file, evidence}.
    """
    tl = table_name.lower()
    readers: List[dict] = []
    writers: List[dict] = []

    for fact in facts:
        if fact.type not in _TABLE_FACT_TYPES:
            continue
        if tl not in fact.target.lower():
            continue
        sym = symbols.get(fact.owner)
        entry = {
            "owner_id": fact.owner,
            "owner_name": sym.name if sym else fact.owner,
            "file": sym.file if sym else "",
            "evidence": fact.evidence,
        }
        if fact.type == "READS_TABLE":
            readers.append(entry)
        else:
            writers.append(entry)

    return {"readers": readers, "writers": writers}
