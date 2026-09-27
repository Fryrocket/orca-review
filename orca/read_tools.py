from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from .executor import CommandSpec, LocalReadOnlyExecutor


class WorkspaceReadTools:
    max_file_chars = 32_000
    max_search_files = 2_000
    max_matches = 100

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError("tool workspace must be an existing directory")
        self.executor = LocalReadOnlyExecutor(self.root)

    def _path(self, value: str) -> Path:
        if not isinstance(value, str) or not value or len(value) > 1_000:
            raise ValueError("path must be bounded text")
        candidate = (self.root / value).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PermissionError("path escapes the tool workspace")
        return candidate

    def read_file(self, *, path: str) -> dict:
        target = self._path(path)
        if not target.is_file():
            raise FileNotFoundError("workspace file was not found")
        content = target.read_text(errors="replace")
        return {"path": str(target.relative_to(self.root)),
                "content": content[:self.max_file_chars],
                "truncated": len(content) > self.max_file_chars}

    def search_files(self, *, query: str, glob: str = "*") -> dict:
        if not isinstance(query, str) or not query or len(query) > 500:
            raise ValueError("search query must be bounded text")
        if not isinstance(glob, str) or not glob or len(glob) > 200:
            raise ValueError("search glob must be bounded text")
        matches = []
        scanned = 0
        for path in self.root.rglob("*"):
            if scanned >= self.max_search_files or len(matches) >= self.max_matches:
                break
            if not path.is_file() or not fnmatch(str(path.relative_to(self.root)), glob):
                continue
            scanned += 1
            try:
                content = path.read_text(errors="replace")[:128_000]
            except OSError:
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if query.lower() in line.lower():
                    matches.append({"path": str(path.relative_to(self.root)),
                                    "line": number, "text": line[:500]})
                    if len(matches) >= self.max_matches:
                        break
        return {"query": query, "matches": matches, "scanned_files": scanned}

    def inspect_terminal(self, *, executable: str, args: list[str]) -> dict:
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError("terminal arguments must be a list of text")
        return self.executor.execute(CommandSpec(executable, executable, tuple(args)))

    def handlers(self) -> dict:
        return {
            "file.read": self.read_file,
            "file.search": self.search_files,
            "repo.read": self.inspect_terminal,
            "terminal.inspect": self.inspect_terminal,
        }
