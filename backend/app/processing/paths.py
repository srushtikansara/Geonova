"""Configurable storage layout: <data_dir>/raw, processed/{indices,changes,summaries}."""
from dataclasses import dataclass
from pathlib import Path

from .errors import InputError


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def raw(self) -> Path: return self.root / "raw"
    @property
    def indices(self) -> Path: return self.root / "processed" / "indices"
    @property
    def changes(self) -> Path: return self.root / "processed" / "changes"
    @property
    def summaries(self) -> Path: return self.root / "processed" / "summaries"

    def ensure(self) -> "DataPaths":
        for p in (self.raw, self.indices, self.changes, self.summaries):
            p.mkdir(parents=True, exist_ok=True)
        return self

    def rel(self, p: Path) -> str:
        """Reference stored in the database / API: relative to the data root, POSIX style."""
        return Path(p).resolve().relative_to(self.root.resolve()).as_posix()

    def resolve_ref(self, ref: str, under: Path | None = None) -> Path:
        """Resolve a user-supplied relative reference, refusing absolute paths and traversal."""
        base = (under or self.root).resolve()
        if not ref or Path(ref).is_absolute() or ".." in Path(ref).parts:
            raise InputError("Path must be relative and must not contain '..'.")
        p = (base / ref).resolve()
        if base != p and base not in p.parents:
            raise InputError("Path escapes the data directory.")
        return p
