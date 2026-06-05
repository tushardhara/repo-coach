"""Python AST parser for RepoCoach v2."""
import ast
import os
import warnings
from typing import List, Optional

from core.graph.schema import Symbol
from core.parsers.base import BaseParser, ParseResult, RawCall, RawImport


def _pkg_from_path(rel_path: str) -> str:
    """Return dotted module path from relative file path."""
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) == 1:
        return ""  # root-level file, no package
    # Strip .py extension from filename part
    filename = parts[-1]
    if filename.endswith(".py"):
        filename = filename[:-3]
    # __init__ represents the package itself, not a sub-module
    if filename == "__init__":
        dotted = ".".join(parts[:-1])
    else:
        dotted = ".".join(parts[:-1] + [filename])
    return dotted


def _args_signature(args: ast.arguments) -> str:
    """Reconstruct arg names (no types) from ast.arguments."""
    names: List[str] = []
    # positional-only args (Python 3.8+)
    for a in getattr(args, "posonlyargs", []):
        names.append(a.arg)
    for a in args.args:
        names.append(a.arg)
    if args.vararg:
        names.append(f"*{args.vararg.arg}")
    for a in args.kwonlyargs:
        names.append(a.arg)
    if args.kwarg:
        names.append(f"**{args.kwarg.arg}")
    return ", ".join(names)


class _CallCollector(ast.NodeVisitor):
    """Walk a function/method body and collect RawCall instances."""

    def __init__(self, caller_id: str, rel_path: str):
        self.caller_id = caller_id
        self.rel_path = rel_path
        self.calls: List[RawCall] = []

    def visit_Call(self, node: ast.Call):
        callee_name = ""
        callee_pkg = ""
        call_text = ""

        func = node.func
        if isinstance(func, ast.Name):
            callee_name = func.id
            call_text = func.id
        elif isinstance(func, ast.Attribute):
            callee_name = func.attr
            if isinstance(func.value, ast.Name):
                callee_pkg = func.value.id
                call_text = f"{func.value.id}.{func.attr}"
            else:
                call_text = f"<expr>.{func.attr}"

        if callee_name:
            self.calls.append(RawCall(
                caller_id=self.caller_id,
                call_text=call_text,
                callee_name=callee_name,
                callee_pkg=callee_pkg,
                line=node.lineno,
                file=self.rel_path,
            ))
        # Recurse into sub-expressions
        self.generic_visit(node)


class PythonParser(BaseParser):
    language = "python"

    def parse_file(self, abs_path: str, rel_path: str, content: str) -> ParseResult:
        result = ParseResult()
        pkg = _pkg_from_path(rel_path)

        try:
            tree = ast.parse(content, filename=abs_path)
        except SyntaxError:
            return result

        # ── Imports ────────────────────────────────────────────────────────
        seen_imports: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    key = (alias.name, alias.asname or "")
                    if key not in seen_imports:
                        seen_imports.add(key)
                        result.imports.append(RawImport(
                            file=rel_path,
                            imported_path=alias.name,
                            alias=alias.asname or "",
                            language="python",
                        ))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                key = (mod, "")
                if key not in seen_imports:
                    seen_imports.add(key)
                    result.imports.append(RawImport(
                        file=rel_path,
                        imported_path=mod,
                        alias="",
                        language="python",
                    ))

        # ── Symbols & Calls ────────────────────────────────────────────────
        # Walk top-level nodes only; recurse manually to track class scope.
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                self._process_function(node, rel_path, pkg, receiver="", result=result)

            elif isinstance(node, ast.ClassDef):
                class_name = node.name
                class_id = self.make_symbol_id("python", "class", rel_path, class_name)
                result.symbols.append(Symbol(
                    id=class_id,
                    kind="class",
                    name=class_name,
                    file=rel_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    signature=f"class {class_name}",
                    package=pkg,
                    language="python",
                ))
                # Methods inside class
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._process_function(child, rel_path, pkg, receiver=class_name, result=result)

        return result

    def _process_function(
        self,
        node,
        rel_path: str,
        pkg: str,
        receiver: str,
        result: ParseResult,
    ):
        name = node.name
        kind = "method" if receiver else "function"
        sym_id = self.make_symbol_id("python", kind, rel_path, name, receiver)
        sig_args = _args_signature(node.args)
        signature = f"def {name}({sig_args})"

        result.symbols.append(Symbol(
            id=sym_id,
            kind=kind,
            name=name,
            file=rel_path,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            signature=signature,
            package=pkg,
            receiver=receiver,
            language="python",
        ))

        # Collect calls from function body
        collector = _CallCollector(caller_id=sym_id, rel_path=rel_path)
        for child in ast.iter_child_nodes(node):
            collector.visit(child)
        result.calls.extend(collector.calls)


# NOTE: registration happens in registry.py to avoid circular import issues.
