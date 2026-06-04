"""Detect queue/SQS/Kafka publish and consume operations."""
import re
from typing import List, Tuple

from core.graph.schema import Fact, Relation, Symbol


_PUBLISH_RE = re.compile(
    r'\b(sqs|kafka|producer|queue|mq|pubsub|bus)\.'
    r'(SendMessage|Produce|Publish|Send|Enqueue|Put)\s*\(',
    re.IGNORECASE,
)
# Also catch method-only patterns on any receiver
_PUBLISH_METHOD_RE = re.compile(
    r'\.(SendMessage|Produce|Publish|Enqueue)\s*\(',
    re.IGNORECASE,
)

_CONSUME_RE = re.compile(
    r'\b(consumer|subscriber|sqs|kafka)\.'
    r'(Subscribe|ReceiveMessage|Consume|Poll|Receive)\s*\(',
    re.IGNORECASE,
)
_CONSUME_METHOD_RE = re.compile(
    r'\.(ReceiveMessage|Subscribe|Consume|Poll)\s*\(',
    re.IGNORECASE,
)

# String literals near calls to extract queue/topic names
_STRING_RE = re.compile(r'["\']([A-Za-z0-9_\-./]{3,80})["\']')


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


def _extract_queue_name(lines: List[str], line_idx: int) -> str:
    """Look in current line ± 3 lines for a string that looks like a queue name."""
    start = max(0, line_idx - 1)
    end = min(len(lines), line_idx + 3)
    for raw in lines[start:end]:
        for m in _STRING_RE.finditer(raw):
            val = m.group(1)
            # Heuristic: queue names usually have underscores, hyphens, or "queue"/"topic" in name
            if (
                any(c in val for c in ("_", "-"))
                or "queue" in val.lower()
                or "topic" in val.lower()
                or "sqs" in val.lower()
            ):
                return val
    # Fallback: any string literal on the triggering line
    for m in _STRING_RE.finditer(lines[line_idx - 1]):
        return m.group(1)
    return "unknown"


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
        owner = _enclosing_symbol(i, file_symbols, rel_path)

        # Publish
        if _PUBLISH_RE.search(line) or _PUBLISH_METHOD_RE.search(line):
            queue = _extract_queue_name(lines, i)
            key = (owner, "PUBLISHES_QUEUE", queue)
            if key not in seen:
                seen.add(key)
                facts.append(Fact(
                    owner=owner,
                    type="PUBLISHES_QUEUE",
                    target=queue,
                    evidence=line.strip(),
                    line=i,
                ))
            continue  # don't also emit CONSUMES on same line

        # Consume
        if _CONSUME_RE.search(line) or _CONSUME_METHOD_RE.search(line):
            queue = _extract_queue_name(lines, i)
            key = (owner, "CONSUMES_QUEUE", queue)
            if key not in seen:
                seen.add(key)
                facts.append(Fact(
                    owner=owner,
                    type="CONSUMES_QUEUE",
                    target=queue,
                    evidence=line.strip(),
                    line=i,
                ))

    return facts, []
