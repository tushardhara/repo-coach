"""Core tool engine for RepoCoach navigator."""
import json
import os
from collections import deque
from typing import Dict, List, Optional, Tuple

from core.graph.schema import Symbol, Relation, Fact, Flow, FileRecord
from core.navigator.locator import locate
from core.index.file_index import load_file_index
from core.index.symbol_index import load_symbol_index
from core.index.relation_index import load_relation_index
from core.index.fact_index import load_fact_index
from core.index.flow_index import load_flow_index

OUTPUT_DIR = ".repo-coach"

VALID_TOOLS = {
    "find_files",
    "find_symbols",
    "find_routes",
    "get_symbol",
    "get_code",
    "get_callees",
    "get_callers",
    "get_facts",
    "search_table",
    "build_flow",
    "build_impact",
}


class GraphStore:
    def __init__(self, repo_root: str):
        self.repo_root = os.path.abspath(repo_root)
        self._load()

    def _out(self, name: str) -> str:
        return os.path.join(self.repo_root, OUTPUT_DIR, name)

    def _load(self):
        self.files: Dict[str, FileRecord] = {}
        self.symbols: Dict[str, Symbol] = {}
        self.symbols_by_name: Dict[str, List[Symbol]] = {}
        self.relations: List[Relation] = []
        self.callee_map: Dict[str, List[Relation]] = {}   # from_id → outgoing CALLS
        self.caller_map: Dict[str, List[Relation]] = {}   # to_id → incoming CALLS
        self.facts: Dict[str, List[Fact]] = {}            # owner → facts
        self.flows: Dict[str, Flow] = {}
        self.unresolved: List[dict] = []
        # route symbol id → handler symbol id
        self._route_to_handler: Dict[str, str] = {}
        # handler symbol id → route symbol id
        self._handler_to_route: Dict[str, str] = {}

        for fr in load_file_index(self._out("file_index.jsonl")):
            self.files[fr.path] = fr

        for sym in load_symbol_index(self._out("symbols.jsonl")):
            self.symbols[sym.id] = sym
            self.symbols_by_name.setdefault(sym.name.lower(), []).append(sym)

        for rel in load_relation_index(self._out("relations.jsonl")):
            self.relations.append(rel)
            if rel.type == "CALLS":
                self.callee_map.setdefault(rel.from_id, []).append(rel)
                self.caller_map.setdefault(rel.to_id, []).append(rel)
            elif rel.type == "EXPOSES_ROUTE":
                self._handler_to_route[rel.from_id] = rel.to_id
                self._route_to_handler[rel.to_id] = rel.from_id

        for fact in load_fact_index(self._out("facts.jsonl")):
            self.facts.setdefault(fact.owner, []).append(fact)

        for flow in load_flow_index(self._out("flows.jsonl")):
            self.flows[flow.id] = flow

        try:
            from core.graph.schema import read_jsonl
            for rec in read_jsonl(self._out("unresolved.jsonl")):
                self.unresolved.append(rec)
        except Exception:
            pass

    def is_ready(self) -> bool:
        return bool(self.symbols)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _sym_dict(self, sym: Symbol) -> dict:
        return {
            "id": sym.id,
            "kind": sym.kind,
            "name": sym.name,
            "file": sym.file,
            "signature": sym.signature,
            "start_line": sym.start_line,
            "end_line": sym.end_line,
        }

    # ── tools ─────────────────────────────────────────────────────────────────

    def find_symbols(self, query: str, limit: int = 10) -> List[dict]:
        """Case-insensitive substring search on name, file, kind."""
        q = query.lower()
        exact, starts, contains = [], [], []

        for sym in self.symbols.values():
            name_l = sym.name.lower()
            file_l = sym.file.lower()
            kind_l = sym.kind.lower()
            hit = (q in name_l) or (q in file_l) or (q in kind_l)
            if not hit:
                continue
            d = self._sym_dict(sym)
            if name_l == q:
                exact.append(d)
            elif name_l.startswith(q):
                starts.append(d)
            else:
                contains.append(d)

        results = exact + starts + contains
        return results[:limit]

    def find_files(self, query: str, top: int = 5) -> list:
        return locate(self, query, top=top)

    def find_routes(self, query: str, limit: int = 10) -> List[dict]:
        """Search route symbols by name/id. Also find handlers via EXPOSES_ROUTE."""
        q = query.lower()
        out = []
        seen = set()

        for sym in self.symbols.values():
            if sym.kind != "route":
                continue
            if q not in sym.name.lower() and q not in sym.id.lower():
                continue
            handler_id = self._route_to_handler.get(sym.id, "")
            handler = self.symbols.get(handler_id)
            entry = {
                "route_id": sym.id,
                "method": "",
                "path": sym.name,
                "handler_id": handler_id,
                "handler_name": handler.name if handler else "",
                "handler_file": handler.file if handler else "",
            }
            # try to parse method from route name e.g. "POST /api/..."
            parts = sym.name.split(None, 1)
            if len(parts) == 2 and parts[0].upper() in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                entry["method"] = parts[0].upper()
                entry["path"] = parts[1]
            if sym.id not in seen:
                seen.add(sym.id)
                out.append(entry)
            if len(out) >= limit:
                break

        return out

    def get_symbol(self, symbol_id: str) -> dict:
        """Full symbol details + related counts."""
        sym = self.symbols.get(symbol_id)
        if not sym:
            return {"error": "not found"}
        return {
            "id": sym.id,
            "kind": sym.kind,
            "name": sym.name,
            "file": sym.file,
            "start_line": sym.start_line,
            "end_line": sym.end_line,
            "signature": sym.signature,
            "package": sym.package,
            "receiver": sym.receiver,
            "callee_count": len(self.callee_map.get(symbol_id, [])),
            "caller_count": len(self.caller_map.get(symbol_id, [])),
            "fact_count": len(self.facts.get(symbol_id, [])),
        }

    def get_code(self, symbol_id: str) -> str:
        """Read source lines for symbol. Max 80 lines."""
        sym = self.symbols.get(symbol_id)
        if not sym:
            return f"error: symbol {symbol_id!r} not found"
        src = os.path.join(self.repo_root, sym.file)
        try:
            with open(src, encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except FileNotFoundError:
            return f"error: file {sym.file!r} not found"

        start = max(0, sym.start_line - 1)
        end = min(len(all_lines), sym.end_line)
        snippet = all_lines[start:end]

        MAX_LINES = 200
        if len(snippet) > MAX_LINES:
            snippet = snippet[:MAX_LINES]
            snippet.append(f"// ... truncated (showing {MAX_LINES} of {end - start} lines)\n")

        return "".join(snippet)

    def get_callees(self, symbol_id: str, depth: int = 1) -> List[dict]:
        """BFS following CALLS edges. Max 50 nodes."""
        if symbol_id not in self.symbols:
            return []
        visited = {symbol_id}
        queue = deque([(symbol_id, 0)])
        results = []

        while queue and len(results) < 50:
            cur_id, cur_depth = queue.popleft()
            if cur_depth >= depth:
                continue
            for rel in self.callee_map.get(cur_id, []):
                nxt = rel.to_id
                if nxt in visited:
                    continue
                visited.add(nxt)
                sym = self.symbols.get(nxt)
                if sym is None:
                    continue
                results.append({
                    "id": sym.id,
                    "name": sym.name,
                    "file": sym.file,
                    "depth": cur_depth + 1,
                    "via_relation_evidence": rel.evidence,
                })
                queue.append((nxt, cur_depth + 1))
                if len(results) >= 50:
                    break

        return results

    def get_callers(self, symbol_id: str, depth: int = 1) -> List[dict]:
        """BFS following CALLS edges backward. Max 50 nodes."""
        if symbol_id not in self.symbols:
            return []
        visited = {symbol_id}
        queue = deque([(symbol_id, 0)])
        results = []

        while queue and len(results) < 50:
            cur_id, cur_depth = queue.popleft()
            if cur_depth >= depth:
                continue
            for rel in self.caller_map.get(cur_id, []):
                nxt = rel.from_id
                if nxt in visited:
                    continue
                visited.add(nxt)
                sym = self.symbols.get(nxt)
                if sym is None:
                    continue
                results.append({
                    "id": sym.id,
                    "name": sym.name,
                    "file": sym.file,
                    "depth": cur_depth + 1,
                })
                queue.append((nxt, cur_depth + 1))
                if len(results) >= 50:
                    break

        return results

    def get_facts(self, symbol_id: str) -> List[dict]:
        """Facts for symbol + direct callees."""
        all_facts = list(self.facts.get(symbol_id, []))
        for rel in self.callee_map.get(symbol_id, []):
            all_facts.extend(self.facts.get(rel.to_id, []))
        seen, out = set(), []
        for f in all_facts:
            key = (f.owner, f.type, f.target)
            if key not in seen:
                seen.add(key)
                out.append({"owner": f.owner, "type": f.type, "target": f.target,
                            "evidence": f.evidence, "line": f.line})
        return out

    def search_table(self, table_name: str) -> dict:
        """Find facts referencing table_name. Group into readers/writers."""
        tl = table_name.lower()
        readers, writers = [], []
        for owner_id, flist in self.facts.items():
            sym = self.symbols.get(owner_id)
            file_ = sym.file if sym else ""
            for f in flist:
                if tl not in f.target.lower():
                    continue
                entry = {"owner": owner_id, "file": file_, "evidence": f.evidence}
                if f.type == "READS_TABLE":
                    readers.append(entry)
                elif f.type == "WRITES_TABLE":
                    writers.append(entry)
        return {"readers": readers, "writers": writers}

    def build_flow(self, entrypoint_id: str) -> dict:
        """Return pre-built flow or compute on-the-fly via BFS."""
        # Try exact match by id
        if entrypoint_id in self.flows:
            return self.flows[entrypoint_id].to_dict()

        # Try match by entrypoint field
        for flow in self.flows.values():
            if flow.entrypoint == entrypoint_id:
                return flow.to_dict()

        # Symbol must exist
        sym = self.symbols.get(entrypoint_id)
        if not sym:
            return {"error": f"entrypoint {entrypoint_id!r} not found"}

        # BFS compute
        chain = []
        visited = {entrypoint_id}
        queue = deque([(entrypoint_id, 0)])
        db_reads, db_writes, redis_keys, queues, events, http_calls = [], [], [], [], [], []
        evidence = []

        FACT_MAP = {
            "READS_TABLE": db_reads,
            "WRITES_TABLE": db_writes,
            "USES_REDIS": redis_keys,
            "PUBLISHES_QUEUE": queues,
            "CONSUMES_QUEUE": queues,
            "PUBLISHES_EVENT": events,
            "CALLS_HTTP": http_calls,
        }

        while queue:
            cur_id, depth = queue.popleft()
            chain.append(cur_id)
            for f in self.facts.get(cur_id, []):
                lst = FACT_MAP.get(f.type)
                if lst is not None and f.target not in lst:
                    lst.append(f.target)
                if f.evidence:
                    evidence.append(f.evidence)
            if depth >= 8 or len(chain) >= 30:
                continue
            for rel in self.callee_map.get(cur_id, []):
                if rel.to_id not in visited and rel.to_id in self.symbols:
                    visited.add(rel.to_id)
                    queue.append((rel.to_id, depth + 1))

        route_sym = self.symbols.get(self._handler_to_route.get(entrypoint_id, ""))
        route_str = route_sym.name if route_sym else ""

        flow = Flow(
            id=f"flow:{entrypoint_id}",
            entrypoint=entrypoint_id,
            route=route_str,
            chain=chain,
            db_reads=list(dict.fromkeys(db_reads)),
            db_writes=list(dict.fromkeys(db_writes)),
            redis=list(dict.fromkeys(redis_keys)),
            queues=list(dict.fromkeys(queues)),
            events=list(dict.fromkeys(events)),
            http_calls=list(dict.fromkeys(http_calls)),
            unresolved=[],
            confidence=1.0,
            evidence=evidence,
        )
        return flow.to_dict()

    def build_impact(self, symbol_id: str) -> dict:
        """BFS backward up to depth 5, find affected routes."""
        sym = self.symbols.get(symbol_id)
        if not sym:
            return {"error": f"symbol {symbol_id!r} not found"}

        visited = {symbol_id}
        queue = deque([(symbol_id, 0)])
        direct_callers = []
        all_callers = []
        depth_reached = 0

        while queue:
            cur_id, depth = queue.popleft()
            if depth >= 5:
                depth_reached = max(depth_reached, depth)
                continue
            for rel in self.caller_map.get(cur_id, []):
                nxt = rel.from_id
                if nxt in visited:
                    continue
                visited.add(nxt)
                caller_sym = self.symbols.get(nxt)
                if caller_sym is None:
                    continue
                entry = {"id": caller_sym.id, "name": caller_sym.name, "file": caller_sym.file}
                all_callers.append(entry)
                if depth == 0:
                    direct_callers.append(entry)
                depth_reached = max(depth_reached, depth + 1)
                queue.append((nxt, depth + 1))

        # Find affected routes via EXPOSES_ROUTE
        affected_routes = []
        seen_routes = set()
        for entry in all_callers:
            handler_id = entry["id"]
            route_id = self._handler_to_route.get(handler_id)
            if route_id and route_id not in seen_routes:
                seen_routes.add(route_id)
                route_sym = self.symbols.get(route_id)
                affected_routes.append({
                    "route_id": route_id,
                    "route_name": route_sym.name if route_sym else route_id,
                    "handler_id": handler_id,
                })

        return {
            "symbol": {"id": sym.id, "name": sym.name, "file": sym.file},
            "direct_callers": direct_callers,
            "all_callers": all_callers,
            "affected_routes": affected_routes,
            "depth_reached": depth_reached,
        }

    # ── dispatch ──────────────────────────────────────────────────────────────

    def dispatch_tool(self, tool_name: str, args: dict) -> str:
        """Call tool by name, return JSON string result."""
        if tool_name not in VALID_TOOLS:
            return json.dumps({"error": f"unknown tool {tool_name!r}. Valid: {sorted(VALID_TOOLS)}"})

        try:
            if tool_name == "find_files":
                result = self.find_files(args.get("query", ""), args.get("top", 5))
            elif tool_name == "find_symbols":
                result = self.find_symbols(args.get("query", ""), args.get("limit", 10))
            elif tool_name == "find_routes":
                result = self.find_routes(args.get("query", ""), args.get("limit", 10))
            elif tool_name == "get_symbol":
                result = self.get_symbol(args.get("symbol_id", ""))
            elif tool_name == "get_code":
                result = self.get_code(args.get("symbol_id", ""))
            elif tool_name == "get_callees":
                result = self.get_callees(args.get("symbol_id", ""), args.get("depth", 1))
            elif tool_name == "get_callers":
                result = self.get_callers(args.get("symbol_id", ""), args.get("depth", 1))
            elif tool_name == "get_facts":
                result = self.get_facts(args.get("symbol_id", ""))
            elif tool_name == "search_table":
                result = self.search_table(args.get("table_name", ""))
            elif tool_name == "build_flow":
                result = self.build_flow(args.get("entrypoint_id", ""))
            elif tool_name == "build_impact":
                result = self.build_impact(args.get("symbol_id", ""))
        except Exception as exc:
            result = {"error": str(exc)}

        return json.dumps(result, ensure_ascii=False)
