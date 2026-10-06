"""Content-hash manifest so reruns only regenerate what actually changed."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import config


def sha(*parts: str | bytes) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8") if isinstance(part, str) else part)
        h.update(b"\x1f")
    return h.hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Stats:
    written: int = 0
    skipped: int = 0
    removed: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return (
            f"{self.written} written, {self.skipped} unchanged, "
            f"{self.removed} removed, {self.failed} failed"
        )


@dataclass
class Manifest:
    """Tracks, per logical unit, the key it was built from and the files it produced.

    Paths are stored relative to the build root so the manifest stays portable.
    """

    path: Path = config.MANIFEST_JSON
    root: Path = config.BUILD
    entries: dict[str, dict] = field(default_factory=dict)
    seen: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path = config.MANIFEST_JSON, root: Path = config.BUILD) -> "Manifest":
        entries: dict[str, dict] = {}
        if path.exists():
            try:
                entries = json.loads(path.read_text(encoding="utf-8")).get("entries", {})
            except (OSError, ValueError):
                entries = {}
        return cls(path=path, root=root, entries=entries)

    def _rel(self, file: Path) -> str:
        try:
            return file.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return file.resolve().as_posix()

    def is_current(self, unit: str, key: str) -> bool:
        """True when this unit was last built from `key` and its outputs survive."""
        entry = self.entries.get(unit)
        if not entry or entry.get("key") != key:
            return False
        for rel in entry.get("files", []):
            if not (self.root / rel).exists():
                return False
        return True

    def record(self, unit: str, key: str, files: list[Path]) -> None:
        self.entries[unit] = {"key": key, "files": [self._rel(f) for f in files]}
        self.seen.add(unit)

    def touch(self, unit: str) -> None:
        """Mark an unchanged unit as still live so prune() keeps it."""
        self.seen.add(unit)

    def prune(self, scope: str) -> list[Path]:
        """Delete outputs of units under `scope` that this run did not produce."""
        removed: list[Path] = []
        for unit in [u for u in self.entries if u.startswith(scope) and u not in self.seen]:
            for rel in self.entries[unit].get("files", []):
                target = self.root / rel
                if target.exists():
                    target.unlink()
                    removed.append(target)
            del self.entries[unit]
        return removed

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "entries": dict(sorted(self.entries.items()))}
        self.path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def write_if_changed(path: Path, data: bytes) -> bool:
    """Write only when content differs. Returns True if the file was written."""
    if path.exists() and path.stat().st_size == len(data) and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def remove_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        try:
            next(directory.iterdir())
        except StopIteration:
            directory.rmdir()
