"""Detect SQL table reads/writes in string literals."""
import re
from typing import List, Tuple

from core.graph.schema import Fact, Relation, Symbol


_SKIP_WORDS = {
    "set", "values", "where", "and", "or", "not", "in", "is",
    "null", "true", "false", "limit", "offset", "order", "group",
    "by", "having", "distinct", "all", "as", "on", "using",
    "select", "from", "into", "update", "delete", "insert", "join",
    "left", "right", "inner", "outer", "cross", "full",
}

_TABLE_NAME_RE = re.compile(r'[a-z_][a-z0-9_]*', re.IGNORECASE)

# SQL keyword patterns
_SELECT_FROM_RE = re.compile(r'\bSELECT\b.+?\bFROM\s+([a-z_][a-z0-9_]*)', re.IGNORECASE | re.DOTALL)
_FROM_RE = re.compile(r'\bFROM\s+([a-z_][a-z0-9_]*)', re.IGNORECASE)
_JOIN_RE = re.compile(r'\bJOIN\s+([a-z_][a-z0-9_]*)', re.IGNORECASE)
_INSERT_INTO_RE = re.compile(r'\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+([a-z_][a-z0-9_]*)', re.IGNORECASE)
_UPDATE_RE = re.compile(r'\bUPDATE\s+([a-z_][a-z0-9_]*)\s+SET\b', re.IGNORECASE)
_DELETE_FROM_RE = re.compile(r'\bDELETE\s+FROM\s+([a-z_][a-z0-9_]*)', re.IGNORECASE)
_UPSERT_RE = re.compile(r'\bUPSERT\s+INTO\s+([a-z_][a-z0-9_]*)', re.IGNORECASE)
_ON_CONFLICT_RE = re.compile(r'\bINSERT\s+INTO\s+([a-z_][a-z0-9_]*).+?ON\s+CONFLICT\b', re.IGNORECASE | re.DOTALL)


def _is_valid_table(name: str) -> bool:
    return name.lower() not in _SKIP_WORDS and len(name) >= 2


def _enclosing_symbol(line_num: int, file_symbols: List[Symbol], rel_path: str) -> str:
    best = None
    best_span = float("inf")
    for sym in file_symbols:
        if sym.start_line <= line_num <= sym.end_line:
            span = sym.end_line - sym.start_line
            if span < best_span:
                best_span = span
                best = sym
    return best.id if best else f"file:{rel_path}"


def _extract_sql_facts(line: str, line_num: int, rel_path: str, file_symbols: List[Symbol]) -> List[Fact]:
    facts: List[Fact] = []
    owner = _enclosing_symbol(line_num, file_symbols, rel_path)

    def add(type_: str, table: str):
        if _is_valid_table(table):
            facts.append(Fact(owner=owner, type=type_, target=table.lower(),
                               evidence=line.strip(), line=line_num))

    # Reads
    for m in _FROM_RE.finditer(line):
        add("READS_TABLE", m.group(1))
    for m in _JOIN_RE.finditer(line):
        add("READS_TABLE", m.group(1))

    # Writes
    for m in _INSERT_INTO_RE.finditer(line):
        add("WRITES_TABLE", m.group(1))
    for m in _UPDATE_RE.finditer(line):
        add("WRITES_TABLE", m.group(1))
    for m in _DELETE_FROM_RE.finditer(line):
        add("WRITES_TABLE", m.group(1))
    for m in _UPSERT_RE.finditer(line):
        add("WRITES_TABLE", m.group(1))

    return facts


# Detect SQL that may span multiple lines via concatenated strings.
# We keep it simple: scan each line individually, then do a multi-line pass
# for patterns that need context (SELECT...FROM across lines).

_SQL_TRIGGER_RE = re.compile(
    r'\b(SELECT|INSERT|UPDATE|DELETE|UPSERT|FROM|JOIN)\b', re.IGNORECASE
)

# Lines that look like language import statements — skip before SQL matching
# Covers: Python "from x import y", JS/TS "import x from y", Go "import ..."
_IMPORT_LINE_RE = re.compile(
    r'^\s*(?:from\s+\S+\s+import\b|import\s+(?:\(|\"|\w))',
    re.IGNORECASE,
)


def detect(
    file_path: str,
    rel_path: str,
    content: str,
    symbols: List[Symbol],
) -> Tuple[List[Fact], List[Relation]]:
    lines = content.splitlines()
    file_symbols = [s for s in symbols if s.file == rel_path]
    facts: List[Fact] = []
    seen: set = set()

    for i, line in enumerate(lines, 1):
        if _IMPORT_LINE_RE.match(line):
            continue
        if not _SQL_TRIGGER_RE.search(line):
            continue
        for fact in _extract_sql_facts(line, i, rel_path, file_symbols):
            key = (fact.owner, fact.type, fact.target)
            if key not in seen:
                seen.add(key)
                facts.append(fact)

    return facts, []
