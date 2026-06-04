"""Core data model for RepoCoach v2 Code Knowledge Graph."""
from dataclasses import dataclass, field, asdict
from typing import List, Optional
import json


# ── Symbol kinds ─────────────────────────────────────────────────────────────
SYMBOL_KINDS = {
    "file", "package", "module", "function", "method", "struct",
    "class", "interface", "route", "table", "redis_key", "queue",
    "event", "external_http", "config",
}

# ── Relation types ────────────────────────────────────────────────────────────
RELATION_TYPES = {
    "CONTAINS", "IMPORTS", "CALLS", "IMPLEMENTS",
    "EXPOSES_ROUTE", "TESTED_BY", "DEPENDS_ON",
}

# ── Fact types ────────────────────────────────────────────────────────────────
FACT_TYPES = {
    "READS_TABLE", "WRITES_TABLE", "USES_REDIS",
    "PUBLISHES_QUEUE", "CONSUMES_QUEUE",
    "PUBLISHES_EVENT", "CALLS_HTTP",
}


@dataclass
class FileRecord:
    path: str
    language: str
    sha256: str
    lines: int
    is_test: bool
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"file:{self.path}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Symbol:
    id: str
    kind: str
    name: str
    file: str
    start_line: int
    end_line: int
    signature: str = ""
    summary: str = ""
    package: str = ""
    receiver: str = ""      # Go method receiver type
    language: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Relation:
    from_id: str
    to_id: str
    type: str
    confidence: float = 1.0
    evidence: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["from"] = d.pop("from_id")
        d["to"] = d.pop("to_id")
        return d


@dataclass
class Fact:
    owner: str
    type: str
    target: str
    evidence: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Flow:
    id: str
    entrypoint: str
    route: str = ""
    chain: List[str] = field(default_factory=list)
    db_reads: List[str] = field(default_factory=list)
    db_writes: List[str] = field(default_factory=list)
    redis: List[str] = field(default_factory=list)
    queues: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    http_calls: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    confidence: float = 1.0
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UnresolvedReference:
    source: str
    call_text: str
    line: int
    reason: str
    candidates: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def write_jsonl(path: str, records) -> int:
    """Write list of dataclass instances to JSONL. Returns count written."""
    count = 0
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
            count += 1
    return count


def read_jsonl(path: str) -> List[dict]:
    """Read JSONL file, return list of dicts."""
    records = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except FileNotFoundError:
        pass
    return records
