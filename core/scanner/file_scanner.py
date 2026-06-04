"""Walk a repository root and produce FileRecord instances."""
import hashlib
import os
from pathlib import Path
from typing import Iterator, Set

from core.graph.schema import FileRecord

SKIP_DIRS: Set[str] = {
    ".git", "node_modules", "__pycache__", "dist", "build",
    ".venv", "venv", "vendor", ".repo-coach", ".understand-anything",
    "testdata", "fixtures", "mocks",
}

EXT_LANG = {
    ".go": "go",
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".rb": "ruby",
    ".java": "java",
    ".rs": "rust",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".kt": "kotlin",
    ".swift": "swift",
    ".sh": "shell",
}

TEST_PATTERNS = (
    "_test.go", "_test.py", ".test.js", ".test.ts",
    ".spec.js", ".spec.ts", "test_", "/tests/", "/test/",
)


def _is_test(path: str) -> bool:
    lp = path.lower()
    return any(p in lp for p in TEST_PATTERNS)


def _sha256(filepath: str) -> str:
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _count_lines(filepath: str) -> int:
    try:
        with open(filepath, "rb") as f:
            return f.read().count(b"\n")
    except OSError:
        return 0


def scan_repo(root: str, max_file_bytes: int = 2_000_000) -> Iterator[FileRecord]:
    """Yield FileRecord for every source file under root."""
    root_path = Path(root).resolve()

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune skip dirs in-place
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
        ]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()
            lang = EXT_LANG.get(ext)
            if lang is None:
                continue

            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if size > max_file_bytes:
                continue

            rel = str(fpath.relative_to(root_path))
            yield FileRecord(
                path=rel,
                language=lang,
                sha256=_sha256(str(fpath)),
                lines=_count_lines(str(fpath)),
                is_test=_is_test(rel),
            )
