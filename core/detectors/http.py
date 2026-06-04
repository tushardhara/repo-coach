"""Detect outbound HTTP calls (Go net/http, resty, JS fetch/axios, Python requests)."""
import re
from typing import List, Tuple

from core.graph.schema import Fact, Relation, Symbol


_HTTP_CALL_RE = re.compile(
    r'\b(http|client|httpClient|resty|curl|hc|c)\.'
    r'(Get|Post|Put|Delete|Patch|Do|Execute|Request|NewRequest|R)\s*\(',
    re.IGNORECASE,
)

# JS/TS fetch and axios
_FETCH_RE = re.compile(r'\bfetch\s*\(', re.IGNORECASE)
_AXIOS_RE = re.compile(
    r'\baxios\.(get|post|put|delete|patch|request|head|options)\s*\(',
    re.IGNORECASE,
)

# Python requests
_REQUESTS_RE = re.compile(
    r'\brequests\.(get|post|put|delete|patch|head|options|request)\s*\(',
    re.IGNORECASE,
)

# URL extraction: https?://... or a variable holding a URL-like string
_URL_RE = re.compile(r'["\']?(https?://[^\s"\')\]]+)["\']?')
_STRING_RE = re.compile(r'["\']([^"\']{4,200})["\']')


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


def _extract_url(line: str) -> str:
    m = _URL_RE.search(line)
    if m:
        return m.group(1)
    # Try any string that starts with http
    for m2 in _STRING_RE.finditer(line):
        val = m2.group(1)
        if val.startswith("http") or val.startswith("/api") or val.startswith("/v"):
            return val
    return "external_http"


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
        is_http = (
            _HTTP_CALL_RE.search(line)
            or _FETCH_RE.search(line)
            or _AXIOS_RE.search(line)
            or _REQUESTS_RE.search(line)
        )
        if not is_http:
            continue

        url = _extract_url(line)
        owner = _enclosing_symbol(i, file_symbols, rel_path)
        key = (owner, "CALLS_HTTP", url)
        if key not in seen:
            seen.add(key)
            facts.append(Fact(
                owner=owner,
                type="CALLS_HTTP",
                target=url,
                evidence=line.strip(),
                line=i,
            ))

    return facts, []
