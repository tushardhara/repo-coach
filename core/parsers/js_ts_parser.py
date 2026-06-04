"""JavaScript/TypeScript parser for RepoCoach v2.

DOWNGRADE NOTICE: tree-sitter is NOT installed.
All extraction uses regex/heuristic scanning — confidence = CONFIDENCE_REGEX (0.7).
Handles: .js, .jsx, .ts, .tsx

Limitations:
  - Class method detection uses brace-depth tracking, not an AST. Deeply nested
    object literals or decorators may cause false positives or missed methods.
  - Arrow functions assigned to object properties (foo.bar = () => {}) are not
    captured as named symbols.
  - Default exports (export default function) are captured but named "<default>".
  - Dynamic require() / import() calls are not tracked.
  - Decorator-based route registration (NestJS, etc.) is not extracted.
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple

from core.graph.schema import Symbol
from core.parsers.base import BaseParser, ParseResult, RawCall, RawImport

# ── Constants ─────────────────────────────────────────────────────────────────

_JS_KEYWORDS = frozenset({
    "if", "for", "while", "switch", "catch", "console",
    "typeof", "instanceof", "return", "new", "delete",
    "throw", "void", "in", "of", "await", "yield",
    "import", "export", "class", "function", "const",
    "let", "var", "async", "static", "get", "set",
    "super", "this", "null", "undefined", "true", "false",
})

# ── Patterns ──────────────────────────────────────────────────────────────────

# import X from 'path' | import { X } from 'path' | import * as X from 'path'
_RE_IMPORT_ES = re.compile(
    r"""^[ \t]*import\s+(.+?)\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# const X = require('path') | const { X } = require('path')
_RE_REQUIRE = re.compile(
    r"""^[ \t]*(?:const|let|var)\s+(\{[^}]+\}|\w+)\s*=\s*require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
    re.MULTILINE,
)

# Named function declaration: function foo(
_RE_FUNC_DECL = re.compile(
    r"""^[ \t]*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+(\w+)\s*\(""",
    re.MULTILINE,
)

# Arrow / function expression: const foo = async? (  or  const foo = function(
_RE_FUNC_ARROW = re.compile(
    r"""^[ \t]*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function\s*)?\(""",
    re.MULTILINE,
)

# class Foo  or  class Foo extends Bar
_RE_CLASS = re.compile(
    r"""^[ \t]*(?:export\s+(?:default\s+)?)?class\s+(\w+)(?:\s+extends\s+\w+)?\s*\{""",
    re.MULTILINE,
)

# Method inside class body (1–2 leading spaces / tabs, optional async/static/get/set)
_RE_METHOD = re.compile(
    r"""^[ \t]+(?:(?:static|async|get|set)\s+)*(\w+)\s*\(""",
    re.MULTILINE,
)

# Express-style route: app.get('/path', ...) or router.post('/path', ...)
_RE_ROUTE = re.compile(
    r"""(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""",
)

# Qualified call: pkg.method(
_RE_CALL_QUALIFIED = re.compile(r'(\w+)\.(\w+)\s*\(')

# Bare call: func(
_RE_CALL_BARE = re.compile(r'(?<!\.)(?<!\w)(\w+)\s*\(')


class JsTsParser(BaseParser):
    language: str = "js"  # overridden per-file based on extension

    # ── public entry point ────────────────────────────────────────────────────

    def parse_file(self, abs_path: str, rel_path: str, content: str) -> ParseResult:
        lang = _detect_lang(abs_path)
        lines = content.splitlines()
        result = ParseResult()

        result.imports = self._extract_imports(content, rel_path, lang)
        symbols = self._extract_symbols(lines, rel_path, lang, content)
        result.symbols = symbols
        result.calls = self._extract_calls(lines, symbols, rel_path)
        return result

    # ── imports ───────────────────────────────────────────────────────────────

    def _extract_imports(self, content: str, rel_path: str, lang: str) -> List[RawImport]:
        imports: List[RawImport] = []
        seen: set = set()

        def _add(alias: str, path: str) -> None:
            if path in seen:
                return
            seen.add(path)
            imports.append(RawImport(
                file=rel_path,
                imported_path=path,
                alias=alias,
                language=lang,
            ))

        # ES imports
        for m in _RE_IMPORT_ES.finditer(content):
            binding = m.group(1).strip()
            path = m.group(2)
            alias = _parse_import_binding(binding)
            _add(alias, path)

        # require()
        for m in _RE_REQUIRE.finditer(content):
            binding = m.group(1).strip()
            path = m.group(2)
            alias = _parse_import_binding(binding)
            _add(alias, path)

        return imports

    # ── symbols ───────────────────────────────────────────────────────────────

    def _extract_symbols(
        self, lines: List[str], rel_path: str, lang: str, content: str
    ) -> List[Symbol]:
        symbols: List[Symbol] = []
        n = len(lines)

        # ── Classes + their methods (needs interleaved scan) ──────────────────
        # Find all class declarations; then scan their bodies for methods.
        class_ranges: List[Tuple[str, int, int]] = []  # (ClassName, start_line, end_line)

        i = 0
        while i < n:
            stripped = lines[i].lstrip()
            m_class = re.match(
                r'(?:export\s+(?:default\s+)?)?class\s+(\w+)',
                stripped,
            )
            if m_class:
                cls_name = m_class.group(1)
                start_line = i + 1
                end_line = _find_block_end(lines, i)
                sym_id = self.make_symbol_id(lang, "class", rel_path, cls_name)
                symbols.append(Symbol(
                    id=sym_id,
                    kind="class",
                    name=cls_name,
                    file=rel_path,
                    start_line=start_line,
                    end_line=end_line,
                    signature=f"class {cls_name}",
                    language=lang,
                ))
                class_ranges.append((cls_name, start_line, end_line))

                # Extract methods within this class body
                for j in range(i + 1, min(end_line, n)):
                    m_method = _RE_METHOD.match(lines[j])
                    if m_method:
                        method_name = m_method.group(1)
                        if method_name in _JS_KEYWORDS or method_name == "constructor":
                            continue
                        m_start = j + 1
                        m_end = _find_block_end(lines, j)
                        m_id = self.make_symbol_id(lang, "method", rel_path, method_name, cls_name)
                        symbols.append(Symbol(
                            id=m_id,
                            kind="method",
                            name=method_name,
                            file=rel_path,
                            start_line=m_start,
                            end_line=m_end,
                            signature=f"{cls_name}.{method_name}()",
                            receiver=cls_name,
                            language=lang,
                        ))
                i = end_line  # jump past class body
                continue
            i += 1

        # Set of line numbers occupied by class bodies (to skip for func extraction)
        class_body_lines: set = set()
        for _, cs, ce in class_ranges:
            for ln in range(cs, ce + 1):
                class_body_lines.add(ln)

        # ── Named function declarations ───────────────────────────────────────
        for m in _RE_FUNC_DECL.finditer("\n".join(lines)):
            func_name = m.group(1)
            line_no = m.string[:m.start()].count("\n") + 1  # 1-indexed
            if line_no in class_body_lines:
                continue
            end_line = _find_block_end(lines, line_no - 1)
            sym_id = self.make_symbol_id(lang, "function", rel_path, func_name)
            symbols.append(Symbol(
                id=sym_id,
                kind="function",
                name=func_name,
                file=rel_path,
                start_line=line_no,
                end_line=end_line,
                signature=f"function {func_name}()",
                language=lang,
            ))

        # ── Arrow / function expression ───────────────────────────────────────
        for m in _RE_FUNC_ARROW.finditer("\n".join(lines)):
            func_name = m.group(1)
            line_no = m.string[:m.start()].count("\n") + 1
            if line_no in class_body_lines:
                continue
            # Avoid double-counting names already captured by _RE_FUNC_DECL
            if any(s.name == func_name and s.kind == "function" for s in symbols):
                continue
            end_line = _find_block_end(lines, line_no - 1)
            sym_id = self.make_symbol_id(lang, "function", rel_path, func_name)
            symbols.append(Symbol(
                id=sym_id,
                kind="function",
                name=func_name,
                file=rel_path,
                start_line=line_no,
                end_line=end_line,
                signature=f"const {func_name} = ()",
                language=lang,
            ))

        # ── Route registrations ───────────────────────────────────────────────
        for idx, line in enumerate(lines):
            m = _RE_ROUTE.search(line)
            if m:
                http_method = m.group(1).upper()
                path = m.group(2)
                route_id = f"route:{http_method}:{path}"
                symbols.append(Symbol(
                    id=route_id,
                    kind="route",
                    name=f"{http_method} {path}",
                    file=rel_path,
                    start_line=idx + 1,
                    end_line=idx + 1,
                    signature=f"{http_method} {path}",
                    language=lang,
                ))

        return symbols

    # ── calls ─────────────────────────────────────────────────────────────────

    def _extract_calls(
        self, lines: List[str], symbols: List[Symbol], rel_path: str
    ) -> List[RawCall]:
        calls: List[RawCall] = []
        func_syms = [s for s in symbols if s.kind in ("function", "method")]

        for sym in func_syms:
            for line_no in range(sym.start_line, sym.end_line + 1):
                idx = line_no - 1
                if idx < 0 or idx >= len(lines):
                    continue
                calls.extend(
                    self._extract_calls_from_line(lines[idx], line_no, sym.id, rel_path)
                )

        return calls

    def _extract_calls_from_line(
        self, line: str, line_no: int, caller_id: str, rel_path: str
    ) -> List[RawCall]:
        calls: List[RawCall] = []
        seen_positions: set = set()

        # Qualified: obj.method(
        for m in _RE_CALL_QUALIFIED.finditer(line):
            pkg = m.group(1)
            name = m.group(2)
            if name in _JS_KEYWORDS or pkg in _JS_KEYWORDS:
                continue
            seen_positions.add(m.start(2))
            calls.append(RawCall(
                caller_id=caller_id,
                call_text=m.group(0),
                callee_name=name,
                callee_pkg=pkg,
                line=line_no,
                file=rel_path,
            ))

        # Bare: func(
        for m in _RE_CALL_BARE.finditer(line):
            name = m.group(1)
            if name in _JS_KEYWORDS:
                continue
            if m.start(1) in seen_positions:
                continue
            calls.append(RawCall(
                caller_id=caller_id,
                call_text=m.group(0),
                callee_name=name,
                callee_pkg="",
                line=line_no,
                file=rel_path,
            ))

        return calls


# ── Module-level helpers ──────────────────────────────────────────────────────

def _detect_lang(path: str) -> str:
    ext = Path(path).suffix.lower()
    return "ts" if ext in (".ts", ".tsx") else "js"


def _parse_import_binding(binding: str) -> str:
    """Extract a usable alias from an import binding string.

    Examples:
        'express'           -> 'express'
        '{ Router }'        -> 'Router'
        '* as fs'           -> 'fs'
        '{ a, b }'          -> 'a'   (first named)
        'React, { useEffect }' -> 'React'
    """
    binding = binding.strip()
    # * as alias
    m = re.search(r'\*\s+as\s+(\w+)', binding)
    if m:
        return m.group(1)
    # Default + named: strip the { ... } part and take default
    default_part = re.sub(r'\{[^}]*\}', '', binding).strip().rstrip(',').strip()
    if default_part and re.match(r'^\w+$', default_part):
        return default_part
    # Named only { X, Y } → first name
    m = re.search(r'\{\s*(\w+)', binding)
    if m:
        return m.group(1)
    return binding


def _find_block_end(lines: List[str], start_idx: int) -> int:
    """Return 1-indexed line number of the closing } that matches the first {
    encountered at or after start_idx."""
    depth = 0
    in_string_char: Optional[str] = None
    found_open = False
    n = len(lines)
    for i in range(start_idx, n):
        line = lines[i]
        j = 0
        while j < len(line):
            ch = line[j]
            # Track string literals (simplistic: no multiline template literals)
            if in_string_char is None:
                if ch in ('"', "'", '`'):
                    in_string_char = ch
                elif ch == '{':
                    depth += 1
                    found_open = True
                elif ch == '}':
                    depth -= 1
                    if found_open and depth == 0:
                        return i + 1  # 1-indexed
            else:
                if ch == '\\':
                    j += 1  # skip escaped char
                elif ch == in_string_char:
                    in_string_char = None
            j += 1
    return n  # fallback
