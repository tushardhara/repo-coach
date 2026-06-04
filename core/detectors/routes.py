"""Detect route handler registrations (Go Fiber/Gin/Chi, Express, FastAPI)."""
import re
from typing import List, Tuple

from core.graph.schema import Fact, Relation, Symbol


# ── helpers ──────────────────────────────────────────────────────────────────

def _enclosing_symbol(line_num: int, file_symbols: List[Symbol], rel_path: str) -> str:
    """Return id of innermost symbol enclosing line_num, or file:<rel_path>."""
    best: Symbol | None = None
    best_span = float("inf")
    for sym in file_symbols:
        if sym.start_line <= line_num <= sym.end_line:
            span = sym.end_line - sym.start_line
            if span < best_span:
                best_span = span
                best = sym
    return best.id if best else f"file:{rel_path}"


def _symbol_by_name(name: str, file_symbols: List[Symbol]) -> str | None:
    """Return id of first symbol matching name in the file, or None."""
    for sym in file_symbols:
        if sym.name == name:
            return sym.id
    return None


def _make_route_symbol(method: str, path: str, rel_path: str, line: int) -> Symbol:
    route_id = f"route:{method}:{path}"
    return Symbol(
        id=route_id,
        kind="route",
        name=f"{method} {path}",
        file=rel_path,
        start_line=line,
        end_line=line,
        language="",
    )


# ── Go / Fiber / Gin / Chi ────────────────────────────────────────────────────

_GO_ROUTE_RE = re.compile(
    r'\.(Get|Post|Put|Delete|Patch|Options|Head|GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)'
    r'\s*\(\s*["`\']([^"`\']+)["`\']\s*,\s*(\w+)',
    re.IGNORECASE,
)


def _detect_go(lines: List[str], rel_path: str, file_symbols: List[Symbol]) -> Tuple[List[Symbol], List[Relation]]:
    route_symbols: List[Symbol] = []
    relations: List[Relation] = []
    for i, line in enumerate(lines, 1):
        for m in _GO_ROUTE_RE.finditer(line):
            method = m.group(1).upper()
            path = m.group(2)
            handler_name = m.group(3)
            rsym = _make_route_symbol(method, path, rel_path, i)
            route_symbols.append(rsym)
            from_id = _symbol_by_name(handler_name, file_symbols) or _enclosing_symbol(i, file_symbols, rel_path)
            relations.append(Relation(
                from_id=from_id,
                to_id=rsym.id,
                type="EXPOSES_ROUTE",
                confidence=0.9,
                evidence=line.strip(),
                line=i,
            ))
    return route_symbols, relations


# ── Express / JS / TS ─────────────────────────────────────────────────────────

_EXPRESS_ROUTE_RE = re.compile(
    r'(app|router|server)\.(get|post|put|delete|patch|options|head)'
    r'\s*\(\s*[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)


def _detect_express(lines: List[str], rel_path: str, file_symbols: List[Symbol]) -> Tuple[List[Symbol], List[Relation]]:
    route_symbols: List[Symbol] = []
    relations: List[Relation] = []
    for i, line in enumerate(lines, 1):
        for m in _EXPRESS_ROUTE_RE.finditer(line):
            method = m.group(2).upper()
            path = m.group(3)
            rsym = _make_route_symbol(method, path, rel_path, i)
            route_symbols.append(rsym)
            from_id = _enclosing_symbol(i, file_symbols, rel_path)
            relations.append(Relation(
                from_id=from_id,
                to_id=rsym.id,
                type="EXPOSES_ROUTE",
                confidence=0.85,
                evidence=line.strip(),
                line=i,
            ))
    return route_symbols, relations


# ── FastAPI / Python ──────────────────────────────────────────────────────────

_FASTAPI_DECORATOR_RE = re.compile(
    r'@(app|router|api_router)\.(get|post|put|delete|patch|options|head)'
    r'\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_DEF_RE = re.compile(r'^\s*(?:async\s+)?def\s+(\w+)')


def _detect_fastapi(lines: List[str], rel_path: str, file_symbols: List[Symbol]) -> Tuple[List[Symbol], List[Relation]]:
    route_symbols: List[Symbol] = []
    relations: List[Relation] = []
    for i, line in enumerate(lines, 1):
        m = _FASTAPI_DECORATOR_RE.search(line)
        if not m:
            continue
        method = m.group(2).upper()
        path = m.group(3)
        rsym = _make_route_symbol(method, path, rel_path, i)
        route_symbols.append(rsym)

        # Look for the def on subsequent non-blank lines
        handler_name: str | None = None
        for j in range(i, min(i + 5, len(lines))):
            dm = _DEF_RE.match(lines[j])
            if dm:
                handler_name = dm.group(1)
                break

        from_id = (
            _symbol_by_name(handler_name, file_symbols)
            if handler_name
            else None
        ) or _enclosing_symbol(i, file_symbols, rel_path)

        relations.append(Relation(
            from_id=from_id,
            to_id=rsym.id,
            type="EXPOSES_ROUTE",
            confidence=0.9,
            evidence=line.strip(),
            line=i,
        ))
    return route_symbols, relations


# ── public API ────────────────────────────────────────────────────────────────

def detect(
    file_path: str,
    rel_path: str,
    content: str,
    symbols: List[Symbol],
) -> Tuple[List[Fact], List[Relation]]:
    """Detect route registrations; returns (facts=[], extra_relations+route_symbols)."""
    lines = content.splitlines()
    file_symbols = [s for s in symbols if s.file == rel_path]

    route_syms: List[Symbol] = []
    relations: List[Relation] = []

    ext = rel_path.rsplit(".", 1)[-1].lower()
    if ext in ("go",):
        rs, rl = _detect_go(lines, rel_path, file_symbols)
        route_syms += rs
        relations += rl
    elif ext in ("js", "ts", "jsx", "tsx", "mjs", "cjs"):
        rs, rl = _detect_express(lines, rel_path, file_symbols)
        route_syms += rs
        relations += rl
    elif ext in ("py",):
        rs, rl = _detect_fastapi(lines, rel_path, file_symbols)
        route_syms += rs
        relations += rl
    else:
        # Try all — unknown extension
        for fn in (_detect_go, _detect_express, _detect_fastapi):
            rs, rl = fn(lines, rel_path, file_symbols)
            route_syms += rs
            relations += rl

    # Route symbols are injected as Relations with special to_id; caller merges them.
    # We also surface them via the relation list so builder can store them.
    # Facts list is empty — routes emit Relations, not Facts.
    return [], relations
