"""File-level locator: ranks files for a natural-language question using lexical + centrality + role signals."""
import math
import os
import re
from collections import defaultdict

# Trimmed stopword set: question/filler words only. We deliberately KEEP domain
# nouns like "wallet", "auth", "route" because those are the locating signal.
_STOP = {
    "what", "does", "do", "how", "who", "where", "when", "why", "which", "is",
    "are", "the", "a", "an", "this", "that", "these", "those", "and", "or", "for",
    "from", "with", "to", "in", "of", "on", "explain", "tell", "show", "find",
    "give", "list", "describe", "happens", "happen", "work", "works", "working",
    "me", "my", "our", "it", "its", "through", "about", "flow",  # 'flow' is generic
}

# Light nominalization stemming so "resolution" matches "resolve", etc.
_STEM = {
    "assignment": "assign", "creation": "create", "deletion": "delete",
    "validation": "validate", "authentication": "auth", "authorization": "auth",
    "registration": "register", "processing": "process", "handling": "handle",
    "resolution": "resolve", "configuration": "config", "navigation": "navigate",
    "detection": "detect", "extraction": "extract", "indexing": "index",
}

_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+")


def _split_ident(s: str):
    """Break CamelCase / snake_case / kebab into lowercase parts."""
    parts = []
    for chunk in re.split(r"[_\-./]", s):
        parts += [p.lower() for p in _CAMEL.findall(chunk)]
    return [p for p in parts if p]


def extract_keywords(question: str):
    """Multi-keyword extraction (the big win over the current single-token grab)."""
    raw = re.split(r"[^A-Za-z0-9_]+", question)
    kws = []
    for tok in raw:
        if not tok:
            continue
        low = tok.lower()
        low = _STEM.get(low, low)
        if low in _STOP or len(low) < 3:
            continue
        kws.append(low)
        # also add CamelCase sub-parts so "AssignVoucher" matches files named "assign"
        for part in _split_ident(tok):
            p = _STEM.get(part, part)
            if p not in _STOP and len(p) >= 3:
                kws.append(p)
    # dedupe, keep order
    seen, out = set(), []
    for k in kws:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _match(kw: str, target: str) -> float:
    """Substring hit = 1.0; shared 4+ char prefix = 0.6 (cheap fuzzy: resolve~resolution)."""
    if not target:
        return 0.0
    t = target.lower()
    if kw in t:
        return 1.0
    # token-level prefix overlap
    for tok in _split_ident(target):
        if len(tok) >= 4 and len(kw) >= 4 and (tok.startswith(kw[:4]) or kw.startswith(tok[:4])):
            return 0.6
    return 0.0


# ── Weights (tune freely; documented so ranking is explainable) ────────────────
W_BASENAME = 3.0    # keyword in the file's basename — strongest lexical signal
W_DIRPATH  = 1.0    # keyword in the directory path
W_SYMNAME  = 1.5    # keyword in a symbol name inside the file (capped per keyword)
W_IN_DEG   = 1.2    # log in-degree: how many callers reach into this file (hub-ness)
W_OUT_DEG  = 0.8    # log out-degree: orchestrators/handlers fan out a lot
W_ROUTE    = 2.5    # file exposes an HTTP route → entry point for a "flow"
W_FACTS    = 1.0    # file touches DB/redis/queues → does real work in a flow
P_TEST     = 4.0    # penalty: don't return a test file as THE answer


def locate(graph, question: str, top: int = 5):
    """
    Rank files for `question`. Returns list of dicts:
      {file, score, why, key_symbols, tested_by}
    `graph` is a GraphStore (uses .symbols, .files, .callee_map, .caller_map,
    .facts, ._handler_to_route, .relations).
    """
    kws = extract_keywords(question)
    if not kws:
        return []

    # group symbols by file + precompute per-file aggregates
    by_file = defaultdict(list)
    for sym in graph.symbols.values():
        if sym.file:
            by_file[sym.file].append(sym)

    # files that expose a route (any handler symbol in the file)
    route_files = set()
    for handler_id in getattr(graph, "_handler_to_route", {}):
        h = graph.symbols.get(handler_id)
        if h and h.file:
            route_files.add(h.file)

    # tested_by hints: file -> [test files] via TESTED_BY relations (if present)
    tested_by = defaultdict(list)
    for rel in graph.relations:
        if rel.type == "TESTED_BY":
            tgt = graph.symbols.get(rel.to_id)
            tf = tgt.file if tgt else rel.to_id
            src = graph.symbols.get(rel.from_id)
            sf = src.file if src else rel.from_id
            if sf:
                tested_by[sf].append(tf)

    results = []
    for fpath, syms in by_file.items():
        base = os.path.basename(fpath)
        dirp = os.path.dirname(fpath)

        # ── lexical ──────────────────────────────────────────────────────────
        lex, hit_kws = 0.0, []
        for kw in kws:
            s = 0.0
            s += W_BASENAME * _match(kw, base)
            s += W_DIRPATH * _match(kw, dirp)
            sym_hits = sum(1 for sym in syms if _match(kw, sym.name) > 0)
            s += W_SYMNAME * min(sym_hits, 3)  # cap so one mega-file can't dominate
            if s > 0:
                hit_kws.append(kw)
            lex += s
        if lex == 0:
            continue  # must match at least one keyword to be a candidate

        # ── centrality ───────────────────────────────────────────────────────
        in_deg = sum(len(graph.caller_map.get(sym.id, [])) for sym in syms)
        out_deg = sum(len(graph.callee_map.get(sym.id, [])) for sym in syms)
        cen = W_IN_DEG * math.log1p(in_deg) + W_OUT_DEG * math.log1p(out_deg)

        # ── role ─────────────────────────────────────────────────────────────
        role = 0.0
        if fpath in route_files:
            role += W_ROUTE
        if any(graph.facts.get(sym.id) for sym in syms):
            role += W_FACTS

        # ── penalty ──────────────────────────────────────────────────────────
        fr = graph.files.get(fpath)
        pen = P_TEST if (fr and getattr(fr, "is_test", False)) else 0.0

        score = lex + cen + role - pen
        # top symbols in this file by (keyword-match, then degree)
        key_syms = sorted(
            syms,
            key=lambda s: (
                sum(_match(kw, s.name) for kw in kws),
                len(graph.caller_map.get(s.id, [])) + len(graph.callee_map.get(s.id, [])),
            ),
            reverse=True,
        )[:4]

        results.append({
            "file": fpath,
            "score": round(score, 2),
            "why": {
                "lexical": round(lex, 2), "centrality": round(cen, 2),
                "role": round(role, 2), "test_penalty": pen,
                "matched": hit_kws, "in_deg": in_deg, "out_deg": out_deg,
                "exposes_route": fpath in route_files,
            },
            "key_symbols": [s.name for s in key_syms],
            "tested_by": sorted(set(tested_by.get(fpath, []))),
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top]
