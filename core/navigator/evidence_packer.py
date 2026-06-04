"""Format tool evidence into compact context strings for Qwen. No model calls."""
from typing import Dict, List


def _trunc(items: list, max_n: int = 8) -> str:
    if not items:
        return "none"
    shown = items[:max_n]
    rest = len(items) - max_n
    s = ", ".join(str(x) for x in shown)
    if rest > 0:
        s += f" ... and {rest} more"
    return s


def pack_flow_evidence(
    question: str,
    flow: dict,
    facts_by_sym: Dict[str, list],
    code_snippets: Dict[str, str],
) -> str:
    """
    Format structured evidence for a flow question.
    Target: ≤ 2000 tokens.
    """
    lines = []
    lines.append("QUESTION:")
    lines.append(question)
    lines.append("")

    lines.append("CALL FLOW:")
    chain = flow.get("chain", [])
    if not chain:
        lines.append("  (no chain available)")
    else:
        for i, sym_id in enumerate(chain[:20], 1):
            # sym_id is typically "lang:kind:file:name"
            parts = sym_id.split(":", 3)
            label = parts[-1] if parts else sym_id
            lines.append(f"{i}. {sym_id}")
            facts = facts_by_sym.get(sym_id, [])
            if facts:
                fact_strs = [f"{f.get('type','?')}:{f.get('target','?')}" for f in facts[:4]]
                lines.append(f"   facts: [{', '.join(fact_strs)}]")
        remaining = len(chain) - 20
        if remaining > 0:
            lines.append(f"   ... and {remaining} more nodes")
    lines.append("")

    lines.append("SIDE EFFECT SUMMARY:")
    lines.append(f"  DB reads:      {_trunc(flow.get('db_reads', []))}")
    lines.append(f"  DB writes:     {_trunc(flow.get('db_writes', []))}")
    lines.append(f"  Redis:         {_trunc(flow.get('redis', []))}")
    lines.append(f"  Queues:        {_trunc(flow.get('queues', []))}")
    lines.append(f"  Events:        {_trunc(flow.get('events', []))}")
    lines.append(f"  External HTTP: {_trunc(flow.get('http_calls', []))}")
    lines.append("")

    unresolved = flow.get("unresolved", [])
    if unresolved:
        lines.append("UNRESOLVED / LOW CONFIDENCE:")
        for u in unresolved[:8]:
            lines.append(f"  - {u}")
        extra = len(unresolved) - 8
        if extra > 0:
            lines.append(f"  ... and {extra} more")
        lines.append("")

    if code_snippets:
        lines.append("CODE SNIPPETS:")
        total_chars = 0
        for sym_id, code in code_snippets.items():
            if total_chars > 1500:
                lines.append("  (further snippets omitted for brevity)")
                break
            lines.append(f"  [{sym_id}]")
            snippet = code[:600]
            lines.append(snippet)
            total_chars += len(snippet)
        lines.append("")

    return "\n".join(lines)


def pack_impact_evidence(question: str, impact: dict) -> str:
    """Format impact analysis result."""
    lines = []
    lines.append("QUESTION:")
    lines.append(question)
    lines.append("")

    if "error" in impact:
        lines.append(f"ERROR: {impact['error']}")
        return "\n".join(lines)

    sym = impact.get("symbol", {})
    lines.append("TARGET SYMBOL:")
    lines.append(f"  id:   {sym.get('id', '?')}")
    lines.append(f"  name: {sym.get('name', '?')}")
    lines.append(f"  file: {sym.get('file', '?')}")
    lines.append("")

    direct = impact.get("direct_callers", [])
    lines.append(f"DIRECT CALLERS ({len(direct)}):")
    for c in direct[:10]:
        lines.append(f"  - {c['name']} ({c['file']})")
    if len(direct) > 10:
        lines.append(f"  ... and {len(direct) - 10} more")
    lines.append("")

    all_c = impact.get("all_callers", [])
    if len(all_c) > len(direct):
        lines.append(f"ALL CALLERS (depth ≤ {impact.get('depth_reached', '?')}): {len(all_c)} total")
        for c in all_c[:15]:
            lines.append(f"  - {c['name']} ({c['file']})")
        if len(all_c) > 15:
            lines.append(f"  ... and {len(all_c) - 15} more")
        lines.append("")

    routes = impact.get("affected_routes", [])
    lines.append(f"AFFECTED ROUTES ({len(routes)}):")
    if routes:
        for r in routes[:10]:
            lines.append(f"  - {r.get('route_name', r.get('route_id', '?'))}  (handler: {r.get('handler_id', '?')})")
        if len(routes) > 10:
            lines.append(f"  ... and {len(routes) - 10} more")
    else:
        lines.append("  none detected")
    lines.append("")

    return "\n".join(lines)


def pack_table_evidence(question: str, table_result: dict) -> str:
    """Format table search result."""
    lines = []
    lines.append("QUESTION:")
    lines.append(question)
    lines.append("")

    readers = table_result.get("readers", [])
    writers = table_result.get("writers", [])

    lines.append(f"TABLE READERS ({len(readers)}):")
    for r in readers[:10]:
        lines.append(f"  - {r['owner']}  ({r['file']})")
        if r.get("evidence"):
            lines.append(f"    evidence: {r['evidence'][:80]}")
    if len(readers) > 10:
        lines.append(f"  ... and {len(readers) - 10} more")
    lines.append("")

    lines.append(f"TABLE WRITERS ({len(writers)}):")
    for w in writers[:10]:
        lines.append(f"  - {w['owner']}  ({w['file']})")
        if w.get("evidence"):
            lines.append(f"    evidence: {w['evidence'][:80]}")
    if len(writers) > 10:
        lines.append(f"  ... and {len(writers) - 10} more")
    lines.append("")

    return "\n".join(lines)


def pack_symbol_evidence(
    question: str,
    symbol: dict,
    callees: list,
    callers: list,
    facts: list,
) -> str:
    """Format general symbol inspection evidence."""
    lines = []
    lines.append("QUESTION:")
    lines.append(question)
    lines.append("")

    if "error" in symbol:
        lines.append(f"ERROR: {symbol['error']}")
        return "\n".join(lines)

    lines.append("SYMBOL:")
    for key in ("id", "name", "kind", "file", "start_line", "end_line", "signature", "package", "receiver"):
        val = symbol.get(key)
        if val or val == 0:
            lines.append(f"  {key}: {val}")
    lines.append("")

    if callees:
        lines.append(f"CALLS ({len(callees)}):")
        for c in callees[:10]:
            lines.append(f"  -> {c['name']} ({c['file']})")
        if len(callees) > 10:
            lines.append(f"  ... and {len(callees) - 10} more")
        lines.append("")

    if callers:
        lines.append(f"CALLED BY ({len(callers)}):")
        for c in callers[:10]:
            lines.append(f"  <- {c['name']} ({c['file']})")
        if len(callers) > 10:
            lines.append(f"  ... and {len(callers) - 10} more")
        lines.append("")

    if facts:
        lines.append(f"FACTS ({len(facts)}):")
        for f in facts[:12]:
            lines.append(f"  [{f.get('type','?')}] {f.get('target','?')}  ({f.get('evidence','')[:60]})")
        if len(facts) > 12:
            lines.append(f"  ... and {len(facts) - 12} more")
        lines.append("")

    return "\n".join(lines)
