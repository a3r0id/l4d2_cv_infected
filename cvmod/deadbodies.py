"""Detect infected materials that map corpse props also reference.

L4D2 body piles under `models/deadbodies/*` use `bpm_*`, `bpf_*`, `bphm_*`,
and `bphf_*` textures. Those VMTs are patches of `bp_body_include` /
`bp_head_include`, so the include has to stay stock or every pile turns flat.
Live commons use `cim_*` / `cif_*` instead.

We also scan deadbodies MDLs for any other infected materials they reference
(charger lynched, fallen survivor, CEDA faceplate, etc.). Live commons still
get flat colour from their own materials and proxy meshes.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import config, mdl, vpkutil

CACHE_NAME = "deadbody_shared_materials.json"
CACHE_VERSION = 3

# Body-pile textures. Live commons use cim_/cif_ and never these.
# bp_body_include / bp_head_include are the patch parents every pile VMT
# includes, so replacing them recolors corpses we never overrode directly.
_CORPSE_TEXTURE_PREFIXES = ("bp",)


def _cache_path() -> Path:
    return config.WORK / CACHE_NAME


def _pak_mtime_ns() -> int:
    pak = config.GAME_DIR / "pak01_dir.vpk"
    try:
        return pak.stat().st_mtime_ns
    except OSError:
        return 0


def _norm_key(key: str) -> str:
    k = key.replace("\\", "/").strip().strip("/").lower()
    if k.endswith(".vmt") or k.endswith(".vtf"):
        k = k.rsplit(".", 1)[0]
    if k.startswith("materials/"):
        k = k[len("materials/") :]
    return k


def is_corpse_texture_material(key: str) -> bool:
    """True for body-pile textures and their shared include VMTs."""
    k = _norm_key(key)
    if not k.startswith("models/infected/"):
        return False
    stem = k.rsplit("/", 1)[-1]
    return stem.startswith(_CORPSE_TEXTURE_PREFIXES)


def _material_keys_for_model(path: Path) -> set[str]:
    """Resolve texture names on a deadbodies MDL to materials/ keys."""
    try:
        model = mdl.read(path)
    except mdl.MdlError:
        return set()
    keys: set[str] = set()
    for texture in model.textures:
        for candidate in _candidates(model.cdmaterials, texture):
            if candidate.startswith("models/infected/"):
                keys.add(candidate)
    return keys


def _candidates(cdmaterials: list[str], texture: str) -> list[str]:
    tex = _norm_key(texture)
    seen: list[str] = []
    for cd in cdmaterials:
        cdn = cd.replace("\\", "/").strip().strip("/").lower()
        candidate = f"{cdn}/{tex}" if cdn else tex
        candidate = _norm_key(candidate)
        if candidate not in seen:
            seen.append(candidate)
    if tex not in seen:
        seen.append(tex)
    return seen


def _corpse_texture_keys_from_src() -> set[str]:
    """Every bpm_/bpf_ VMT under the extracted infected materials tree."""
    root = config.SRC_MATERIALS / "models" / "infected"
    if not root.exists():
        return set()
    keys: set[str] = set()
    for path in root.rglob("*.vmt"):
        key = path.relative_to(config.SRC_MATERIALS).with_suffix("").as_posix().lower()
        if is_corpse_texture_material(key):
            keys.add(key)
    return keys


def _discover_from_deadbody_models() -> set[str]:
    """Read every deadbodies MDL from the game VPK and collect infected mats."""
    shared: set[str] = set()
    tmp = config.WORK / "_deadbody_probe.mdl"
    config.WORK.mkdir(parents=True, exist_ok=True)
    try:
        pak = vpkutil.index_game_pak()
    except (FileNotFoundError, OSError, RuntimeError):
        return shared
    for rel in sorted(pak):
        if not (rel.startswith("models/deadbodies/") or rel.startswith("models/c1_chargerexit/")):
            continue
        if not rel.endswith(".mdl"):
            continue
        try:
            tmp.write_bytes(vpkutil.read_game_file(rel))
        except (FileNotFoundError, OSError):
            continue
        shared |= _material_keys_for_model(tmp)
    tmp.unlink(missing_ok=True)
    return shared


def _discover() -> set[str]:
    return _corpse_texture_keys_from_src() | _discover_from_deadbody_models()


@lru_cache(maxsize=1)
def shared_infected_materials() -> frozenset[str]:
    """Infected material keys that corpse props use (leave stock)."""
    cache = _cache_path()
    mtime = _pak_mtime_ns()
    if cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            if (
                int(raw.get("cache_version", 0)) == CACHE_VERSION
                and int(raw.get("pak_mtime_ns", -1)) == mtime
                and isinstance(raw.get("materials"), list)
            ):
                return frozenset(_norm_key(str(x)) for x in raw["materials"])
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    shared = sorted(_discover())
    config.WORK.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {
                "cache_version": CACHE_VERSION,
                "pak_mtime_ns": mtime,
                "materials": shared,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    return frozenset(shared)


def is_shared_infected_material(key: str) -> bool:
    k = _norm_key(key)
    if is_corpse_texture_material(k):
        return True
    return k in shared_infected_materials()
