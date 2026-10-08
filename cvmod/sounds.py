"""Convert and install custom sounds from config.json into the game tree."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass(frozen=True)
class SoundEntry:
    name: str
    src: Path
    destinations: tuple[Path, ...]


def _normalize_dest(rel: str) -> str:
    """Game-relative path under GAME_ROOT.

    Accepts `left4dead2/sound/...` or the short `l4d2/sound/...` alias.
    """
    text = rel.replace("\\", "/").lstrip("/")
    if text.startswith("l4d2/"):
        text = "left4dead2/" + text[len("l4d2/") :]
    return text


def entries() -> list[SoundEntry]:
    out: list[SoundEntry] = []
    for name, body in config.CUSTOM_SOUND_GENERATOR.items():
        src = config.HELPERS / str(body["src"])
        dests = tuple(
            config.GAME_ROOT / _normalize_dest(str(dest))
            for dest in body.get("dest", [])
        )
        if not dests:
            continue
        out.append(SoundEntry(name=str(name), src=src, destinations=dests))
    return out


def _ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise FileNotFoundError(
            "ffmpeg not found on PATH; needed to convert custom sounds to WAV"
        )
    return found


def _convert(src: Path, dest: Path) -> None:
    """Write a Source-friendly PCM WAV (16-bit, 44.1 kHz)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".tmp.wav")
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        str(src),
        "-acodec",
        "pcm_s16le",
        "-ar",
        "44100",
        str(tmp),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"ffmpeg failed for {src.name} -> {dest.name}\n{result.stderr[-800:]}"
        )
    tmp.replace(dest)


def _write_dest(src: Path, dest: Path) -> None:
    """Copy into the game tree, with a clearer error when L4D2 has the file open."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".new.wav")
    try:
        shutil.copy2(src, tmp)
        tmp.replace(dest)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise PermissionError(
            f"{dest} is in use, usually because Left 4 Dead 2 is running. "
            "Close the game and deploy again."
        ) from exc


def install() -> list[Path]:
    """Convert each configured source and write every destination path."""
    written: list[Path] = []
    cache = config.WORK / "sounds"
    cache.mkdir(parents=True, exist_ok=True)

    for entry in entries():
        if not entry.src.is_file():
            raise FileNotFoundError(f"custom sound source missing: {entry.src}")
        cached = cache / f"{entry.name}.wav"
        # Rebuild when the source is newer than the cached WAV.
        if (
            not cached.exists()
            or cached.stat().st_mtime < entry.src.stat().st_mtime
        ):
            _convert(entry.src, cached)
        for dest in entry.destinations:
            _write_dest(cached, dest)
            written.append(dest)
    return written


def uninstall() -> list[Path]:
    """Remove loose overrides so the stock VPK sounds take over again."""
    removed: list[Path] = []
    for entry in entries():
        for dest in entry.destinations:
            if not dest.exists():
                continue
            try:
                dest.unlink()
            except OSError as exc:
                raise PermissionError(
                    f"{dest} is in use, usually because Left 4 Dead 2 is running. "
                    "Close the game and deploy again."
                ) from exc
            removed.append(dest)
    return removed


def sync(enabled: bool) -> tuple[list[Path], list[Path]]:
    """Install or remove custom sounds. Returns `(installed, cleaned)`."""
    if enabled:
        return install(), []
    return [], uninstall()
