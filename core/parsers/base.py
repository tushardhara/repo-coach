"""Base contracts for all language parsers."""
from dataclasses import dataclass, field
from typing import List

from core.graph.schema import Symbol


@dataclass
class RawCall:
    caller_id: str      # symbol id of calling function/method
    call_text: str      # full call expression as written in source
    callee_name: str    # just the function name (e.g. "AssignVoucher")
    callee_pkg: str     # package/module qualifier (e.g. "voucher"), empty if unqualified
    line: int
    file: str           # relative path


@dataclass
class RawImport:
    file: str           # relative path of importing file
    imported_path: str  # import path as written (e.g. "github.com/org/repo/core/modules")
    alias: str          # alias or "" (e.g. "modules" or "")
    language: str


@dataclass
class ParseResult:
    symbols: List[Symbol] = field(default_factory=list)
    calls: List[RawCall] = field(default_factory=list)
    imports: List[RawImport] = field(default_factory=list)


class BaseParser:
    language: str = ""
    CONFIDENCE_AST: float = 1.0
    CONFIDENCE_REGEX: float = 0.7

    def parse_file(self, abs_path: str, rel_path: str, content: str) -> ParseResult:
        raise NotImplementedError

    @staticmethod
    def make_symbol_id(lang: str, kind: str, file: str, name: str, receiver: str = "") -> str:
        if receiver:
            return f"{lang}:{kind}:{file}:{receiver}.{name}"
        return f"{lang}:{kind}:{file}:{name}"
