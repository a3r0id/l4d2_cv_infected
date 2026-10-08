"""Paths, tool locations, and tunables loaded from config.json."""

from __future__ import annotations

import json
import os
import re
import winreg
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent
CONFIG_JSON = HELPERS / "config.json"


def _is_game_root(path: Path) -> bool:
    return (path / "left4dead2.exe").is_file() and (path / "bin" / "studiomdl.exe").is_file()


def _steam_libraries() -> list[Path]:
    libraries: list[Path] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam = Path(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        steam = None
    vdf_paths = []
    if steam is not None:
        libraries.append(steam)
        vdf_paths.append(steam / "steamapps" / "libraryfolders.vdf")
    for vdf in vdf_paths:
        if not vdf.is_file():
            continue
        for match in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace")):
            libraries.append(Path(match.group(1).replace("\\\\", "\\")))
    return libraries


def _find_game_root() -> Path | None:
    """The folder that contains left4dead2.exe.

    The project used to live at left4dead2/addons/helpers, three levels under
    that folder. A checkout anywhere else is resolved through Steam app 550,
    or through L4D2_DIR when Steam is not how the game was installed.
    """
    nested = HELPERS.parent.parent.parent
    if _is_game_root(nested):
        return nested
    override = os.environ.get("L4D2_DIR")
    if override and _is_game_root(Path(override)):
        return Path(override)
    for library in _steam_libraries():
        candidate = library / "steamapps" / "common" / "Left 4 Dead 2"
        if _is_game_root(candidate):
            return candidate
    return None


def _rgb(value: list[int] | tuple[int, ...]) -> tuple[int, int, int]:
    if len(value) != 3:
        raise ValueError(f"expected RGB triple, got {value!r}")
    return int(value[0]), int(value[1]), int(value[2])


def _commands(mapping: dict[str, str]) -> list[tuple[str, str]]:
    return [(str(name), str(value)) for name, value in mapping.items()]


def _load_user_config() -> dict:
    if not CONFIG_JSON.is_file():
        raise FileNotFoundError(f"missing {CONFIG_JSON}")
    raw = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{CONFIG_JSON} must contain a JSON object")
    return raw


_USER = _load_user_config()

GAME_ROOT = _find_game_root() or (HELPERS.parent.parent.parent)
GAME_DIR = GAME_ROOT / "left4dead2"
ADDONS_DIR = GAME_DIR / "addons"

# Read-only input: assets extracted out of pak01_dir.vpk.
SRC = HELPERS / "l4d2"
SRC_MATERIALS = SRC / "materials"
SRC_MODELS = SRC / "models"
SRC_INFECTED_MODELS = SRC_MODELS / "infected"

BUILD = HELPERS / "build"
DIST = HELPERS / "dist"
WORK = HELPERS / ".work"
INDEX_JSON = WORK / "index.json"
INDEX_REPORT = WORK / "index_report.txt"
MANIFEST_JSON = WORK / "manifest.json"

STUDIOMDL = GAME_ROOT / "bin" / "studiomdl.exe"
VPK_EXE = GAME_ROOT / "bin" / "vpk.exe"
HLMV = GAME_ROOT / "bin" / "hlmv.exe"
VPKEDIT_CLI = Path(_USER.get("vpkedit_cli", r"C:\Program Files\VPKEdit\vpkeditcli.exe"))

ADDON_NAME = str(_USER.get("addon_name", "cv_infected"))
VPK_PATH = DIST / f"{ADDON_NAME}.vpk"

FLAT_MATERIAL_DIR = str(_USER.get("flat_material_dir", "models/cvmod"))

TRACER_COLOR: tuple[int, int, int] = _rgb(_USER["tracer_color"])
TRACER_SECONDS: float = float(_USER["tracer_seconds"])
LIGHTWARP_COLOR: tuple[int, int, int] = _rgb(_USER["lightwarp_color"])

CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    name: _rgb(color) for name, color in _USER["class_colors"].items()
}
CLASS_PRECEDENCE: dict[str, int] = {
    name: int(rank) for name, rank in _USER["class_precedence"].items()
}

GIB_DIRS = {str(d) for d in _USER["gib_dirs"]}
MATERIAL_EXCLUDE_PREFIXES: tuple[str, ...] = tuple(
    str(p) for p in _USER["material_exclude_prefixes"]
)
MODEL_CLASS_PREFIXES: list[tuple[str, str]] = [
    (str(prefix), str(cls)) for prefix, cls in _USER["model_class_prefixes"]
]

CONSUMABLE_MODEL_STEMS: tuple[str, ...] = tuple(
    str(s) for s in _USER["consumable_model_stems"]
)
CONSUMABLE_MATERIAL_PREFIXES: tuple[str, ...] = tuple(
    str(p) for p in _USER["consumable_material_prefixes"]
)

RENDER_FLAGS: dict[str, str] = {
    str(key): str(value) for key, value in _USER["render_flags"].items()
}
# Always point the self-illum mask at the shared white warp under flat_material_dir.
RENDER_FLAGS["$selfillummask"] = f"{FLAT_MATERIAL_DIR}/flat_lightwarp"

TRACER_MATERIALS: tuple[str, ...] = tuple(str(m) for m in _USER["tracer_materials"])

CAPTURE_COMMANDS: list[tuple[str, str]] = _commands(_USER["capture_commands"])
CLIENT_COMMANDS: tuple[tuple[str, str], ...] = tuple(_commands(_USER["client_commands"]))
CLEANUP_COMMANDS: tuple[tuple[str, str], ...] = tuple(_commands(_USER["cleanup_commands"]))

ALPHA_PRESERVE: set[str] = {str(k) for k in _USER["alpha_preserve"]}
ADDITIVE_PRESERVE: set[str] = {str(k) for k in _USER["additive_preserve"]}

SPITTER_PUDDLE_MATERIALS: tuple[str, ...] = tuple(
    str(m) for m in _USER["spitter_puddle_materials"]
)
SMOKER_TONGUE_MATERIALS: tuple[str, ...] = tuple(
    str(m) for m in _USER["smoker_tongue_materials"]
)

# name -> {src, dest[]}. Installed into the game tree with --feat-sounds.
CUSTOM_SOUND_GENERATOR: dict[str, dict] = {
    str(name): {
        "src": str(body["src"]),
        "dest": [str(d) for d in body.get("dest", [])],
    }
    for name, body in (_USER.get("custom_sound_generator") or {}).items()
}


def classify_model(stem: str, rel_dirs: tuple[str, ...] = ()) -> str:
    """Map a model onto an infected or consumable class.

    `rel_dirs` are the folder names between models/infected/ and the file, which
    is how severed limbs and gibs are told apart from whole bodies.
    """
    if any(d.lower() in GIB_DIRS for d in rel_dirs):
        return "gibs"
    s = stem.lower()
    for prefix, cls in MODEL_CLASS_PREFIXES:
        if s.startswith(prefix):
            return cls
    return "common"


def is_consumable_material(key: str) -> bool:
    k = key.replace("\\", "/").lower()
    return any(k == p or k.startswith(p) for p in CONSUMABLE_MATERIAL_PREFIXES)


def is_excluded_material(key: str) -> bool:
    k = key.replace("\\", "/").lower()
    return k.startswith(MATERIAL_EXCLUDE_PREFIXES) or not k.startswith("models/")


def search_path(path: Path) -> str:
    """A gameinfo `Game` entry for `path`.

    Relative to the install when the tree lives inside it. Absolute otherwise,
    so studiomdl can still see this checkout.
    """
    resolved = path.resolve()
    try:
        text = resolved.relative_to(GAME_ROOT.resolve()).as_posix()
    except ValueError:
        text = resolved.as_posix()
    return f'"{text}"'


def studiomdl_env() -> dict[str, str]:
    env = dict(os.environ)
    env["VPROJECT"] = str(GAME_DIR)
    env["SteamAppId"] = "550"
    return env
