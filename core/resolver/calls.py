"""Resolve raw call expressions into CALLS relations."""
from typing import List, Set, Tuple

from core.graph.schema import Relation, Symbol, UnresolvedReference
from core.parsers.base import RawCall
from core.resolver.symbols import SymbolIndex


# ── Stdlib / builtin skip sets ────────────────────────────────────────────────

_GO_STDLIB: Set[str] = {
    "fmt", "log", "os", "io", "strings", "strconv", "errors", "context",
    "sync", "time", "http", "json", "sort", "math", "bytes", "bufio",
    "filepath", "regexp", "reflect", "atomic",
}

_PYTHON_BUILTINS: Set[str] = {
    "print", "len", "range", "enumerate", "zip", "map", "filter", "sorted",
    "reversed", "list", "dict", "set", "tuple", "str", "int", "float", "bool",
    "open", "super", "hasattr", "getattr", "setattr", "isinstance", "type",
    "repr", "vars",
}

_JS_GLOBALS: Set[str] = {
    "console", "JSON", "Math", "Array", "Object", "String", "Number",
    "Promise", "setTimeout", "clearTimeout", "require", "module", "exports",
    "process",
}

_STDLIB_ALL: Set[str] = _GO_STDLIB | _PYTHON_BUILTINS | _JS_GLOBALS


def _is_stdlib(name: str, pkg: str) -> bool:
    return name in _STDLIB_ALL or pkg in _STDLIB_ALL


# ── Helpers ───────────────────────────────────────────────────────────────────

def _caller_package(caller: Symbol | None) -> str:
    return caller.package if caller else ""


def _caller_file(raw: RawCall) -> str:
    return raw.file


# ── Main resolver ─────────────────────────────────────────────────────────────

def resolve_calls(
    raw_calls: List[RawCall],
    symbols: List[Symbol],
) -> Tuple[List[Relation], List[UnresolvedReference]]:
    """
    Resolve raw call expressions to CALLS relations.

    Resolution order (first match wins):
      1. Same file            confidence=0.95
      2. Same package         confidence=0.85
      3. Import-qualified     confidence=0.80
      4. Receiver/method      confidence=0.75
      5. Fuzzy (case-insensitive) confidence=0.50

    Returns (relations, unresolved_references).
    """
    idx = SymbolIndex(symbols)

    seen_rels: Set[Tuple[str, str, str]] = set()
    relations: List[Relation] = []
    unresolved: List[UnresolvedReference] = []

    def emit(from_id: str, to_id: str, confidence: float, line: int, evidence: str) -> None:
        if from_id == to_id:
            return
        key = (from_id, to_id, "CALLS")
        if key in seen_rels:
            return
        seen_rels.add(key)
        relations.append(Relation(
            from_id=from_id,
            to_id=to_id,
            type="CALLS",
            confidence=confidence,
            evidence=evidence,
            line=line,
        ))

    for rc in raw_calls:
        # Skip stdlib / builtins
        if _is_stdlib(rc.callee_name, rc.callee_pkg):
            continue

        caller_sym = idx.get(rc.caller_id)
        caller_pkg = _caller_package(caller_sym)
        caller_file = _caller_file(rc)
        resolved = False

        # ── Step 1: same file ──────────────────────────────────────────────
        match = idx.find_in_file(caller_file, rc.callee_name)
        if match:
            emit(rc.caller_id, match.id, 0.95, rc.line, f"same-file:{rc.callee_name}")
            resolved = True

        # ── Step 2: same package ───────────────────────────────────────────
        if not resolved and caller_pkg:
            pkg_matches = idx.find_in_package(caller_pkg, rc.callee_name)
            if pkg_matches:
                emit(rc.caller_id, pkg_matches[0].id, 0.85, rc.line,
                     f"same-pkg:{caller_pkg}.{rc.callee_name}")
                resolved = True

        # ── Step 3: import-qualified (callee_pkg is a package qualifier) ────
        if not resolved and rc.callee_pkg:
            pkg_matches = idx.find_in_package(rc.callee_pkg, rc.callee_name)
            if pkg_matches:
                emit(rc.caller_id, pkg_matches[0].id, 0.80, rc.line,
                     f"pkg-qual:{rc.callee_pkg}.{rc.callee_name}")
                resolved = True

        # ── Step 4: receiver / method ──────────────────────────────────────
        if not resolved and rc.callee_pkg:
            # Look for method symbol whose receiver matches callee_pkg
            candidates = [
                s for s in idx.by_name.get(rc.callee_name, [])
                if s.receiver and s.receiver.lower() == rc.callee_pkg.lower()
            ]
            if candidates:
                emit(rc.caller_id, candidates[0].id, 0.75, rc.line,
                     f"receiver:{rc.callee_pkg}.{rc.callee_name}")
                resolved = True

        # ── Step 5: fuzzy (case-insensitive) ──────────────────────────────
        if not resolved:
            fuzzy = idx.find_by_name_fuzzy(rc.callee_name)
            if fuzzy:
                emit(rc.caller_id, fuzzy[0].id, 0.50, rc.line,
                     f"fuzzy:{rc.callee_name}")
                resolved = True

        # ── Unresolved ────────────────────────────────────────────────────
        if not resolved:
            # Gather partial-match candidates by substring on name
            name_lower = rc.callee_name.lower()
            candidates = [
                s.id for s in symbols
                if name_lower in s.name.lower()
            ][:5]
            reason = "no_match"
            if rc.callee_pkg:
                reason = f"pkg_not_found:{rc.callee_pkg}"
            unresolved.append(UnresolvedReference(
                source=rc.caller_id,
                call_text=rc.call_text,
                line=rc.line,
                reason=reason,
                candidates=candidates,
            ))

    return relations, unresolved
