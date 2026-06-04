"""Fast lookup indexes over a Symbol list for resolver use."""
from typing import Dict, List, Optional, Tuple

from core.graph.schema import Symbol


class SymbolIndex:
    def __init__(self, symbols: List[Symbol]) -> None:
        self.by_id: Dict[str, Symbol] = {}
        self.by_name: Dict[str, List[Symbol]] = {}
        self.by_file: Dict[str, List[Symbol]] = {}
        self.by_package: Dict[str, List[Symbol]] = {}
        self.by_file_and_name: Dict[Tuple[str, str], Symbol] = {}

        for sym in symbols:
            # id
            self.by_id[sym.id] = sym

            # name (case-sensitive)
            self.by_name.setdefault(sym.name, []).append(sym)

            # file
            self.by_file.setdefault(sym.file, []).append(sym)

            # package
            if sym.package:
                self.by_package.setdefault(sym.package, []).append(sym)

            # (file, name) — last writer wins for duplicates (shouldn't happen)
            self.by_file_and_name[(sym.file, sym.name)] = sym

        # Lower-cased name map for fuzzy fallback
        self._by_name_lower: Dict[str, List[Symbol]] = {}
        for name, syms in self.by_name.items():
            self._by_name_lower.setdefault(name.lower(), []).extend(syms)

    # ── Public helpers ────────────────────────────────────────────────────────

    def find_by_name(self, name: str) -> List[Symbol]:
        return self.by_name.get(name, [])

    def find_in_file(self, file: str, name: str) -> Optional[Symbol]:
        return self.by_file_and_name.get((file, name))

    def find_in_package(self, package: str, name: str) -> List[Symbol]:
        return [s for s in self.by_package.get(package, []) if s.name == name]

    def find_by_name_fuzzy(self, name: str) -> List[Symbol]:
        """Case-insensitive name lookup."""
        return self._by_name_lower.get(name.lower(), [])

    def get(self, symbol_id: str) -> Optional[Symbol]:
        return self.by_id.get(symbol_id)
