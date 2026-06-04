"""Go language parser for RepoCoach v2.

DOWNGRADE NOTICE: tree-sitter is NOT installed.
All extraction uses regex/heuristic scanning — confidence = CONFIDENCE_REGEX (0.7).
Limitations:
  - Brace-matching is line-by-line; multi-line strings containing braces may
    throw off end_line detection.
  - Generic type parameters (Go 1.18+) in func signatures may confuse the
    method/function regex if the receiver line uses complex generics.
  - Call extraction skips blank lines but does NOT parse expression trees,
    so chained calls like a.b().c() emit two separate calls.
"""

import re
from typing import List, Optional, Tuple

from core.graph.schema import Symbol
from core.parsers.base import BaseParser, ParseResult, RawCall, RawImport

# ── Constants ─────────────────────────────────────────────────────────────────

_GO_KEYWORDS_BUILTINS = frozenset({
    "if", "for", "switch", "select", "go", "defer", "return",
    "make", "append", "len", "cap", "copy", "delete", "close",
    "new", "panic", "recover", "print", "println",
    "range", "break", "continue", "goto", "fallthrough",
    "var", "type", "const", "map", "chan", "func",
})

# ── Patterns ──────────────────────────────────────────────────────────────────

_RE_PACKAGE = re.compile(r'^\s*package\s+(\w+)', re.MULTILINE)

# Single-line import: import "path" or import alias "path"
_RE_IMPORT_SINGLE = re.compile(
    r'^\s*import\s+(?:(\w+)\s+)?"([^"]+)"', re.MULTILINE
)

# import ( ... ) block
_RE_IMPORT_BLOCK = re.compile(
    r'import\s*\(([^)]*)\)', re.DOTALL
)
# One entry inside an import block: optional alias + quoted path
_RE_IMPORT_ENTRY = re.compile(
    r'(?:(\w+|_|\.)\s+)?"([^"]+)"'
)

# func Foo(  — top-level function (no receiver)
_RE_FUNC = re.compile(r'^func\s+(\w+)\s*[\[(]')

# func (v *VoucherService) Foo(  — method with receiver
_RE_METHOD = re.compile(r'^func\s+\((\w+)\s+\*?(\w+)\)\s+(\w+)\s*[\[(]')

# type Foo struct {
_RE_STRUCT = re.compile(r'^type\s+(\w+)\s+struct\s*\{')

# type Foo interface {
_RE_INTERFACE = re.compile(r'^type\s+(\w+)\s+interface\s*\{')

# pkg.Func(  — qualified call
_RE_CALL_QUALIFIED = re.compile(r'(\w+)\.(\w+)\s*\(')

# Func(  — bare call (must not be preceded by '.')
_RE_CALL_BARE = re.compile(r'(?<!\.)(?<!\w)(\w+)\s*\(')


class GoParser(BaseParser):
    language: str = "go"

    # ── public entry point ────────────────────────────────────────────────────

    def parse_file(self, abs_path: str, rel_path: str, content: str) -> ParseResult:
        lines = content.splitlines()
        result = ParseResult()

        pkg = self._extract_package(content)
        result.imports = self._extract_imports(content, rel_path)
        symbols = self._extract_symbols(lines, rel_path, pkg)
        result.symbols = symbols
        result.calls = self._extract_calls(lines, symbols, rel_path)
        return result

    # ── package ───────────────────────────────────────────────────────────────

    def _extract_package(self, content: str) -> str:
        m = _RE_PACKAGE.search(content)
        return m.group(1) if m else ""

    # ── imports ───────────────────────────────────────────────────────────────

    def _extract_imports(self, content: str, rel_path: str) -> List[RawImport]:
        imports: List[RawImport] = []
        seen: set = set()

        def _add(alias: Optional[str], path: str) -> None:
            if path in seen:
                return
            seen.add(path)
            effective_alias = alias if alias and alias not in ("_", ".") else path.split("/")[-1]
            imports.append(RawImport(
                file=rel_path,
                imported_path=path,
                alias=effective_alias,
                language="go",
            ))

        # Grouped import blocks first (remove them so single-line scan doesn't double-count)
        content_without_blocks = content
        for block_match in _RE_IMPORT_BLOCK.finditer(content):
            block_body = block_match.group(1)
            for entry in _RE_IMPORT_ENTRY.finditer(block_body):
                alias_grp = entry.group(1)  # may be None
                path = entry.group(2)
                _add(alias_grp, path)
            # Blank out block so single-line regex doesn't re-match
            content_without_blocks = content_without_blocks.replace(
                block_match.group(0), " " * len(block_match.group(0)), 1
            )

        # Single-line imports
        for m in _RE_IMPORT_SINGLE.finditer(content_without_blocks):
            alias_grp = m.group(1)  # may be None
            path = m.group(2)
            _add(alias_grp, path)

        return imports

    # ── symbols ───────────────────────────────────────────────────────────────

    def _extract_symbols(self, lines: List[str], rel_path: str, pkg: str) -> List[Symbol]:
        symbols: List[Symbol] = []
        n = len(lines)
        i = 0
        while i < n:
            raw = lines[i]
            stripped = raw.lstrip()

            # Method: func (v *Type) Name(
            m_method = _RE_METHOD.match(stripped)
            if m_method:
                receiver_type = m_method.group(2)
                func_name = m_method.group(3)
                start = i + 1  # 1-indexed
                end = self._find_end_line(lines, i)
                sig = self._extract_signature(lines, i)
                sym_id = self.make_symbol_id("go", "method", rel_path, func_name, receiver_type)
                symbols.append(Symbol(
                    id=sym_id,
                    kind="method",
                    name=func_name,
                    file=rel_path,
                    start_line=start,
                    end_line=end,
                    signature=sig,
                    package=pkg,
                    receiver=receiver_type,
                    language="go",
                ))
                i += 1
                continue

            # Function: func Name(
            m_func = _RE_FUNC.match(stripped)
            if m_func:
                func_name = m_func.group(1)
                start = i + 1
                end = self._find_end_line(lines, i)
                sig = self._extract_signature(lines, i)
                sym_id = self.make_symbol_id("go", "function", rel_path, func_name)
                symbols.append(Symbol(
                    id=sym_id,
                    kind="function",
                    name=func_name,
                    file=rel_path,
                    start_line=start,
                    end_line=end,
                    signature=sig,
                    package=pkg,
                    language="go",
                ))
                i += 1
                continue

            # Struct
            m_struct = _RE_STRUCT.match(stripped)
            if m_struct:
                type_name = m_struct.group(1)
                start = i + 1
                end = self._find_block_end(lines, i)
                sym_id = self.make_symbol_id("go", "struct", rel_path, type_name)
                symbols.append(Symbol(
                    id=sym_id,
                    kind="struct",
                    name=type_name,
                    file=rel_path,
                    start_line=start,
                    end_line=end,
                    signature=f"type {type_name} struct",
                    package=pkg,
                    language="go",
                ))
                i += 1
                continue

            # Interface
            m_iface = _RE_INTERFACE.match(stripped)
            if m_iface:
                type_name = m_iface.group(1)
                start = i + 1
                end = self._find_block_end(lines, i)
                sym_id = self.make_symbol_id("go", "interface", rel_path, type_name)
                symbols.append(Symbol(
                    id=sym_id,
                    kind="interface",
                    name=type_name,
                    file=rel_path,
                    start_line=start,
                    end_line=end,
                    signature=f"type {type_name} interface",
                    package=pkg,
                    language="go",
                ))
                i += 1
                continue

            i += 1

        return symbols

    # ── end-line helpers ──────────────────────────────────────────────────────

    def _find_end_line(self, lines: List[str], start_idx: int) -> int:
        """Scan from start_idx, count braces, return 1-indexed line of closing }."""
        depth = 0
        in_string = False
        n = len(lines)
        found_open = False
        for i in range(start_idx, n):
            for ch in lines[i]:
                if ch == '"' and not in_string:
                    in_string = True
                elif ch == '"' and in_string:
                    in_string = False
                if in_string:
                    continue
                if ch == '{':
                    depth += 1
                    found_open = True
                elif ch == '}':
                    depth -= 1
                    if found_open and depth == 0:
                        return i + 1  # 1-indexed
        return n  # fallback: end of file

    def _find_block_end(self, lines: List[str], start_idx: int) -> int:
        """Same as _find_end_line — reused for struct/interface."""
        return self._find_end_line(lines, start_idx)

    # ── signature ─────────────────────────────────────────────────────────────

    def _extract_signature(self, lines: List[str], start_idx: int) -> str:
        """Collect text from 'func' up to (not including) the body opening '{'."""
        sig_parts = []
        n = len(lines)
        for i in range(start_idx, min(start_idx + 8, n)):
            line = lines[i].strip()
            if '{' in line:
                part = line[:line.index('{')].strip()
                if part:
                    sig_parts.append(part)
                break
            sig_parts.append(line)
        return " ".join(sig_parts)

    # ── calls ─────────────────────────────────────────────────────────────────

    def _extract_calls(
        self, lines: List[str], symbols: List[Symbol], rel_path: str
    ) -> List[RawCall]:
        """Scan body of each function/method symbol for call expressions."""
        calls: List[RawCall] = []
        func_syms = [s for s in symbols if s.kind in ("function", "method")]

        for sym in func_syms:
            body_start = sym.start_line      # 1-indexed, inclusive
            body_end = sym.end_line          # 1-indexed, inclusive
            for line_no in range(body_start, body_end + 1):
                idx = line_no - 1
                if idx < 0 or idx >= len(lines):
                    continue
                line = lines[idx]
                calls.extend(
                    self._extract_calls_from_line(line, line_no, sym.id, rel_path)
                )

        return calls

    def _extract_calls_from_line(
        self, line: str, line_no: int, caller_id: str, rel_path: str
    ) -> List[RawCall]:
        calls: List[RawCall] = []
        seen_positions: set = set()

        # Qualified calls first: pkg.Func(
        for m in _RE_CALL_QUALIFIED.finditer(line):
            pkg_name = m.group(1)
            func_name = m.group(2)
            if func_name in _GO_KEYWORDS_BUILTINS or pkg_name in _GO_KEYWORDS_BUILTINS:
                continue
            pos = m.start()
            seen_positions.add(m.start(2))  # track the function-name position
            calls.append(RawCall(
                caller_id=caller_id,
                call_text=m.group(0),
                callee_name=func_name,
                callee_pkg=pkg_name,
                line=line_no,
                file=rel_path,
            ))

        # Bare calls: Func(  — not preceded by '.'
        for m in _RE_CALL_BARE.finditer(line):
            func_name = m.group(1)
            if func_name in _GO_KEYWORDS_BUILTINS:
                continue
            # Skip if this position was already captured by qualified match
            if m.start(1) in seen_positions:
                continue
            calls.append(RawCall(
                caller_id=caller_id,
                call_text=m.group(0),
                callee_name=func_name,
                callee_pkg="",
                line=line_no,
                file=rel_path,
            ))

        return calls
