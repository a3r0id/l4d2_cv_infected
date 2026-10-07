"""Read files out of Left 4 Dead 2's pak01 VPK set."""

from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path

from . import config


def _read_cstr(data: bytes, i: int) -> tuple[str, int]:
    end = data.index(b"\x00", i)
    return data[i:end].decode("ascii", "replace"), end + 1


@lru_cache(maxsize=1)
def index_game_pak() -> dict[str, tuple[int, int, int, bytes]]:
    """Map lowercase relative path -> (archive, offset, length, preload)."""
    dir_path = config.GAME_DIR / "pak01_dir.vpk"
    data = dir_path.read_bytes()
    sig, ver, tree_size = struct.unpack_from("<III", data, 0)
    if sig != 0x55AA1234 or ver != 1:
        raise RuntimeError(f"unsupported VPK at {dir_path}: sig={sig:#x} ver={ver}")
    off = 12
    end = off + tree_size
    out: dict[str, tuple[int, int, int, bytes]] = {}
    i = off
    while i < end:
        ext, i = _read_cstr(data, i)
        if ext == "":
            break
        while i < end:
            path, i = _read_cstr(data, i)
            if path == "":
                break
            while i < end:
                name, i = _read_cstr(data, i)
                if name == "":
                    break
                _crc, preload, arch, offset, length, _term = struct.unpack_from(
                    "<IHHIIH", data, i
                )
                i += 18
                preload_bytes = data[i : i + preload]
                i += preload
                full = f"{path}/{name}.{ext}" if path != " " else f"{name}.{ext}"
                out[full.replace("\\", "/").lower()] = (
                    arch,
                    offset,
                    length,
                    preload_bytes,
                )
    return out


def read_game_file(rel: str) -> bytes:
    key = rel.replace("\\", "/").lower().lstrip("/")
    entry = index_game_pak().get(key)
    if entry is None:
        raise FileNotFoundError(f"{rel} not in game VPK")
    arch, offset, length, preload = entry
    need = length - len(preload)
    if need <= 0:
        return preload[:length]
    if arch == 0x7FFF:
        data = (config.GAME_DIR / "pak01_dir.vpk").read_bytes()
        return preload + data[offset : offset + need]
    pak = config.GAME_DIR / f"pak01_{arch:03d}.vpk"
    with pak.open("rb") as handle:
        handle.seek(offset)
        rest = handle.read(need)
    if len(rest) != need:
        raise OSError(f"short read for {rel}: got {len(rest)}, want {need}")
    return preload + rest


def extract_game_files(
    rel_paths: list[str],
    dest_root: Path,
    *,
    optional: bool = False,
) -> list[Path]:
    """Write relative VPK paths under dest_root. Skips files that already match.

    When `optional` is set, missing VPK entries are skipped instead of raising.
    """
    written: list[Path] = []
    for rel in rel_paths:
        key = rel.replace("\\", "/").lower().lstrip("/")
        dest = dest_root / key
        try:
            data = read_game_file(key)
        except FileNotFoundError:
            if optional:
                continue
            raise
        if dest.exists() and dest.read_bytes() == data:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written.append(dest)
    return written
