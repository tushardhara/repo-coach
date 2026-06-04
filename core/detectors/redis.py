"""Detect Redis operations (Go, Python, JS/TS)."""
import re
from typing import List, Tuple

from core.graph.schema import Fact, Relation, Symbol


_REDIS_CALL_RE = re.compile(
    r'\b(redis|rdb|cache|redisClient|client|r)\.'
    r'(Get|Set|Del|Delete|Pipeline|LPush|RPush|RPopLPush|Incr|Expire'
    r'|HSet|HGet|SAdd|SMembers|ZAdd|ZRange|GetSet|SetNX|SetEX|MGet|MSet'
    r'|Append|Exists|TTL|Keys|Scan|HScan|SScan|ZScan|Watch|TxPipeline)\s*\(',
    re.IGNORECASE,
)

# Python redis-py style: r.get("key"), r.set("key", value)
_PYTHON_REDIS_RE = re.compile(
    r'\b(redis|r|cache|client|rdb)\.(get|set|delete|lpush|rpush|hset|hget|sadd|smembers'
    r'|incr|expire|pipeline|execute_command)\s*\(',
    re.IGNORECASE,
)

# String key in surrounding context (redis key naming conventions)
_KEY_RE = re.compile(r'["\']([a-z_:][a-z0-9_:.\-]{2,60})["\']', re.IGNORECASE)


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


def _extract_key(line: str, operation: str) -> str:
    """Try to extract a meaningful key/operation label from the line."""
    # First look for string literals (likely to be key names)
    keys = _KEY_RE.findall(line)
    # Filter out things that look like URLs or irrelevant strings
    for k in keys:
        if "://" not in k and not k.startswith("/"):
            return k
    return operation.lower()


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
        m = _REDIS_CALL_RE.search(line) or _PYTHON_REDIS_RE.search(line)
        if not m:
            continue
        operation = m.group(2)
        target = _extract_key(line, operation)
        owner = _enclosing_symbol(i, file_symbols, rel_path)
        key = (owner, "USES_REDIS", target)
        if key not in seen:
            seen.add(key)
            facts.append(Fact(
                owner=owner,
                type="USES_REDIS",
                target=target,
                evidence=line.strip(),
                line=i,
            ))

    return facts, []
