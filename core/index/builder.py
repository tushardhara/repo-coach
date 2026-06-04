"""
Build orchestrator — creates .repo-coach/ and writes all index artifacts.

Call order:
  1. Scan files           → file_index.jsonl + manifest.json
  2. Parse symbols        → symbols.jsonl
  3. Resolve relations    → relations.jsonl + unresolved.jsonl
  4. Run detectors        → facts.jsonl
  5. Build flows          → flows.jsonl
"""
import json
import os
import time
from pathlib import Path
from typing import List, Optional

from core.graph.schema import (
    FileRecord, Symbol, Relation, Fact, Flow, UnresolvedReference,
    write_jsonl,
)
from core.index.file_index import write_file_index
from core.index.symbol_index import write_symbol_index
from core.index.relation_index import write_relation_index
from core.index.fact_index import write_fact_index
from core.index.flow_index import write_flow_index
from core.scanner.file_scanner import scan_repo


OUTPUT_DIR = ".repo-coach"


def _out(repo_root: str, name: str) -> str:
    return os.path.join(repo_root, OUTPUT_DIR, name)


def ensure_output_dir(repo_root: str) -> str:
    d = os.path.join(repo_root, OUTPUT_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def build(repo_root: str, verbose: bool = True) -> dict:
    """
    Full build pipeline. Returns stats dict.
    repo_root: absolute path to target repository.
    """
    repo_root = str(Path(repo_root).resolve())
    out_dir = ensure_output_dir(repo_root)

    def log(msg):
        if verbose:
            print(msg, flush=True)

    t0 = time.time()
    log(f"[build] repo: {repo_root}")
    log(f"[build] output: {out_dir}")

    # ── Phase 1: Scan files ────────────────────────────────────────────────
    log("[1/5] Scanning files...")
    files: List[FileRecord] = list(scan_repo(repo_root))
    n_files = write_file_index(_out(repo_root, "file_index.jsonl"), files)
    log(f"      {n_files} source files indexed")

    # ── Phase 2: Parse symbols ─────────────────────────────────────────────
    log("[2/5] Parsing symbols...")
    from core.parsers.registry import parse_all
    symbols, raw_calls, raw_imports = parse_all(repo_root, files, verbose=verbose)
    n_sym = write_symbol_index(_out(repo_root, "symbols.jsonl"), symbols)
    log(f"      {n_sym} symbols extracted")

    # ── Phase 3: Resolve relations ─────────────────────────────────────────
    log("[3/5] Resolving relations...")
    from core.resolver.calls import resolve_calls
    from core.resolver.imports import resolve_imports
    relations: List[Relation] = []
    unresolved: List[UnresolvedReference] = []
    relations += resolve_imports(raw_imports, symbols, files)
    new_relations, new_unresolved = resolve_calls(raw_calls, symbols)
    relations += new_relations
    unresolved += new_unresolved
    n_rel = write_relation_index(_out(repo_root, "relations.jsonl"), relations)
    n_unr = write_jsonl(_out(repo_root, "unresolved.jsonl"), unresolved)
    log(f"      {n_rel} relations, {n_unr} unresolved")

    # ── Phase 4: Detect facts ──────────────────────────────────────────────
    log("[4/5] Detecting side effects...")
    from core.detectors.runner import detect_all
    facts, extra_relations = detect_all(repo_root, files, symbols)
    relations += extra_relations

    # Materialise route symbols from EXPOSES_ROUTE relations so they appear in symbols.jsonl
    existing_ids = {s.id for s in symbols}
    route_syms_map: dict = {}  # route_id → Symbol
    for rel in extra_relations:
        if rel.type == "EXPOSES_ROUTE" and rel.to_id not in existing_ids:
            rid = rel.to_id  # e.g. "route:POST:/assign"
            parts = rid.split(":", 2)
            method = parts[1] if len(parts) > 1 else ""
            path = parts[2] if len(parts) > 2 else rid
            if rid not in route_syms_map:
                route_syms_map[rid] = Symbol(
                    id=rid, kind="route",
                    name=f"{method.upper()} {path}",
                    file="", start_line=0, end_line=0,
                    signature=f"{method.upper()} {path}",
                )
    if route_syms_map:
        symbols += list(route_syms_map.values())
        write_symbol_index(_out(repo_root, "symbols.jsonl"), symbols)
        log(f"      +{len(route_syms_map)} route symbols added")

    n_fact = write_fact_index(_out(repo_root, "facts.jsonl"), facts)
    # Re-write relations now that we have route relations too
    write_relation_index(_out(repo_root, "relations.jsonl"), relations)
    log(f"      {n_fact} facts detected")

    # ── Phase 5: Build flows ───────────────────────────────────────────────
    log("[5/5] Building flows...")
    from core.navigator.flow_navigator import build_all_flows
    flows = build_all_flows(symbols, relations, facts)
    n_flow = write_flow_index(_out(repo_root, "flows.jsonl"), flows)
    log(f"      {n_flow} flows built")

    elapsed = round(time.time() - t0, 1)

    # ── Manifest ───────────────────────────────────────────────────────────
    stats = {
        "repo": repo_root,
        "files": n_files,
        "symbols": n_sym,
        "relations": n_rel,
        "facts": n_fact,
        "flows": n_flow,
        "unresolved": n_unr,
        "elapsed_s": elapsed,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(_out(repo_root, "manifest.json"), "w") as f:
        json.dump(stats, f, indent=2)

    log(f"[build] done in {elapsed}s")
    return stats
