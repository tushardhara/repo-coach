"""Parser registry — maps language -> BaseParser instance."""
import os
import warnings
from typing import Dict, List, Tuple

from core.graph.schema import FileRecord, Symbol
from core.parsers.base import BaseParser, RawCall, RawImport

PARSER_REGISTRY: Dict[str, BaseParser] = {}


def register(parser: BaseParser) -> None:
    """Register a parser instance under its declared language."""
    PARSER_REGISTRY[parser.language] = parser


def parse_all(
    repo_root: str,
    files: List[FileRecord],
    verbose: bool = False,
) -> Tuple[List[Symbol], List[RawCall], List[RawImport]]:
    """Parse every file in *files* using the registered parser for its language.

    Returns (symbols, raw_calls, raw_imports) aggregated across all files.
    Files whose language has no parser are silently skipped.
    Files that raise an exception during parsing log a warning and are skipped.
    """
    all_symbols: List[Symbol] = []
    all_calls: List[RawCall] = []
    all_imports: List[RawImport] = []

    for file_record in files:
        parser = PARSER_REGISTRY.get(file_record.language)
        if parser is None:
            continue

        # file_record.path may be relative or absolute depending on caller
        if os.path.isabs(file_record.path):
            abs_path = file_record.path
            rel_path = os.path.relpath(file_record.path, repo_root)
        else:
            abs_path = os.path.join(repo_root, file_record.path)
            rel_path = file_record.path

        try:
            with open(abs_path, errors="ignore") as fh:
                content = fh.read()
        except OSError as exc:
            warnings.warn(f"Cannot read {abs_path}: {exc}")
            continue

        try:
            result = parser.parse_file(abs_path, rel_path, content)
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"Parser error in {rel_path}: {exc}")
            continue

        all_symbols.extend(result.symbols)
        all_calls.extend(result.calls)
        all_imports.extend(result.imports)

        if verbose:
            print(
                f"  [{file_record.language}] {rel_path}: "
                f"{len(result.symbols)} sym, {len(result.calls)} calls"
            )

    return all_symbols, all_calls, all_imports


# ── Register built-in parsers ──────────────────────────────────────────────────
from core.parsers.python_parser import PythonParser as _PythonParser  # noqa: E402
from core.parsers.go_parser import GoParser as _GoParser              # noqa: E402
from core.parsers.js_ts_parser import JsTsParser as _JsTsParser      # noqa: E402

register(_PythonParser())
register(_GoParser())

# JsTsParser.language == "js" but scan_repo emits "javascript"/"typescript".
# Register the same instance under both scanner language keys.
_jsts = _JsTsParser()
PARSER_REGISTRY["javascript"] = _jsts
PARSER_REGISTRY["typescript"] = _jsts
