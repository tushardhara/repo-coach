"""Detect event publishing (eventBus.Publish, emitter.Emit, etc.)."""
import re
from typing import List, Tuple

from core.graph.schema import Fact, Relation, Symbol


_EVENT_CALL_RE = re.compile(
    r'\b(eventBus|publisher|emitter|dispatcher|bus|events|event_bus|event_emitter)\.'
    r'(Publish|AddEvent|Emit|Dispatch|Fire|Send|Trigger|Raise)\s*\(',
    re.IGNORECASE,
)
# Also catch standalone .AddEvent( and .Publish( near Event struct names
_ADD_EVENT_RE = re.compile(r'\.(AddEvent|Emit|Dispatch|Fire)\s*\(', re.IGNORECASE)

# CamelCase names ending in Event / Message / Notification / EventType
_EVENT_NAME_RE = re.compile(r'\b([A-Z][a-zA-Z0-9]+(?:Event|Message|Notification|EventType))\b')

# String event names: "user.created", "order_placed"
_STRING_EVENT_RE = re.compile(r'["\']([a-z][a-z0-9_.:\-]{2,60})["\']')


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


def _extract_event_name(lines: List[str], line_idx: int) -> str:
    """Look in current line ± 2 lines for a CamelCase Event name or string literal."""
    start = max(0, line_idx - 1)
    end = min(len(lines), line_idx + 2)
    for raw in lines[start:end]:
        m = _EVENT_NAME_RE.search(raw)
        if m:
            return m.group(1)
    # Fall back to string literal
    for raw in lines[start:end]:
        m = _STRING_EVENT_RE.search(raw)
        if m:
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
        if not (_EVENT_CALL_RE.search(line) or _ADD_EVENT_RE.search(line)):
            continue

        # Extra guard for .AddEvent / generic patterns — require Event name nearby
        if not _EVENT_CALL_RE.search(line):
            # Only proceed if there's an event-like name on the line
            if not _EVENT_NAME_RE.search(line):
                continue

        event_name = _extract_event_name(lines, i)
        owner = _enclosing_symbol(i, file_symbols, rel_path)
        key = (owner, "PUBLISHES_EVENT", event_name)
        if key not in seen:
            seen.add(key)
            facts.append(Fact(
                owner=owner,
                type="PUBLISHES_EVENT",
                target=event_name,
                evidence=line.strip(),
                line=i,
            ))

    return facts, []
