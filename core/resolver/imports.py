"""Resolve import statements into IMPORTS and CONTAINS relations."""
from typing import List

from core.graph.schema import FileRecord, Relation, Symbol
from core.parsers.base import RawImport


def resolve_imports(
    raw_imports: List[RawImport],
    symbols: List[Symbol],
    files: List[FileRecord],
) -> List[Relation]:
    """
    Emit:
      IMPORTS  file → file   (one per resolved RawImport)
      CONTAINS file → symbol (one per symbol)

    Deduplicates by (from_id, to_id, type).
    """
    seen: set = set()
    relations: List[Relation] = []

    def add(rel: Relation) -> None:
        key = (rel.from_id, rel.to_id, rel.type)
        if key not in seen:
            seen.add(key)
            relations.append(rel)

    # ── IMPORTS: match imported_path as suffix/substring against FileRecord.path ─
    for imp in raw_imports:
        from_id = f"file:{imp.file}"
        best: FileRecord | None = None

        # Prefer longest suffix match (most specific)
        best_len = 0
        for fr in files:
            ip = imp.imported_path.replace("\\", "/")
            fp = fr.path.replace("\\", "/")
            # normalise: strip leading "./"
            ip_n = ip.lstrip("./")
            fp_n = fp.lstrip("./")
            if fp_n.endswith(ip_n) or ip_n in fp_n:
                if len(ip_n) > best_len:
                    best = fr
                    best_len = len(ip_n)

        if best is not None:
            add(Relation(
                from_id=from_id,
                to_id=f"file:{best.path}",
                type="IMPORTS",
                confidence=0.9,
                evidence=imp.imported_path,
            ))

    # ── CONTAINS: file → every symbol it declares ──────────────────────────
    for sym in symbols:
        add(Relation(
            from_id=f"file:{sym.file}",
            to_id=sym.id,
            type="CONTAINS",
            confidence=1.0,
        ))

    return relations
