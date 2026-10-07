"""Paths, tool locations and the infected class/colour table."""

from __future__ import annotations

import os
import re
import winreg
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent


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
VPKEDIT_CLI = Path(r"C:\Program Files\VPKEdit\vpkeditcli.exe")

ADDON_NAME = "cv_infected"
VPK_PATH = DIST / f"{ADDON_NAME}.vpk"

# Where generated flat textures live inside the addon.
FLAT_MATERIAL_DIR = "models/cvmod"

# Shot traces. Not a class colour, so a frame can separate a bullet path from
# every infected. Beams using this colour last under a second.
TRACER_COLOR: tuple[int, int, int] = (255, 0, 128)
TRACER_SECONDS: float = 0.5

# Listen-server capture settings. Applied by the map script. `exec` cannot read
# a cfg that only exists inside an addon VPK, so these are not a manual step.
# `sv_cheats 1` comes first because `fog_override` is marked as a cheat.
CAPTURE_COMMANDS: list[tuple[str, str]] = [
    ("sv_cheats", "1"),
    ("mat_hdr_level", "0"),
    ("mat_bloomscale", "0"),
    ("mat_disable_bloom", "1"),
    ("mat_colorcorrection", "0"),
    ("mat_motion_blur_enabled", "0"),
    ("mat_grain_scale_override", "0"),
    ("mat_antialias", "0"),
    ("mat_software_aa_strength", "0"),
    ("mat_specular", "0"),
    ("r_dynamic", "0"),
    ("muzzleflash_light", "0"),
    ("fog_override", "1"),
    ("fog_enable", "0"),
    ("r_drawviewmodel", "0"),
    ("cl_drawhud", "0"),
    ("net_graph", "0"),
    ("sv_consistency", "0"),
    ("sv_pure", "0"),
]

# Saturated and mutually separable, and far from L4D2's brown/grey palette.
CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    "common": (255, 0, 255),
    "boomer": (0, 255, 0),
    "hunter": (0, 255, 255),
    "smoker": (255, 128, 0),
    "charger": (255, 0, 0),
    "jockey": (255, 255, 0),
    "spitter": (0, 255, 128),
    "tank": (0, 0, 255),
    "witch": (255, 255, 255),
    "gibs": (128, 0, 255),
    # Bright white so kits and throwables pop through walls. Same RGB as the
    # witch; shape is what separates them in a capture.
    "consumable": (255, 255, 255),
}

# Lower number wins when several models claim the same material. `gibs` ranks
# below `common` on purpose: wound materials are shared between severed limbs
# and living bodies, and the living body is what is on screen most.
CLASS_PRECEDENCE: dict[str, int] = {
    "witch": 0,
    "tank": 1,
    "charger": 2,
    "hunter": 3,
    "smoker": 4,
    "boomer": 5,
    "jockey": 6,
    "spitter": 7,
    "common": 8,
    "gibs": 9,
    "consumable": 10,
}

# Model folders whose contents are dismembered parts rather than whole infected.
GIB_DIRS = {"gibs", "limbs"}

# Materials the pipeline must never touch. `debug/debugempty` is referenced by
# the Charger for a deliberately invisible mesh; flattening it would make that
# mesh render.
MATERIAL_EXCLUDE_PREFIXES: tuple[str, ...] = (
    "debug/",
    "models/debug/",
    "effects/",
    "engine/",
    "tools/",
)

# Model filename stem -> class. Checked as prefixes, longest first.
MODEL_CLASS_PREFIXES: list[tuple[str, str]] = [
    ("anim_common_male_exp", "common"),
    ("anim_common_vomit", "common"),
    ("common_fem_infected", "common"),
    ("common_male_infected", "common"),
    ("common_shadertest", "common"),
    ("anim_common", "common"),
    ("anim_hulk", "tank"),
    ("anim_boomer", "boomer"),
    ("anim_charger", "charger"),
    ("anim_hunter", "hunter"),
    ("anim_jockey", "jockey"),
    ("anim_smoker", "smoker"),
    ("anim_spitter", "spitter"),
    ("anim_witch", "witch"),
    ("boomette", "boomer"),
    ("boomer", "boomer"),
    ("charger", "charger"),
    ("hulk", "tank"),
    ("hunter", "hunter"),
    ("jockey", "jockey"),
    ("smoker", "smoker"),
    ("spitter", "spitter"),
    ("witch", "witch"),
    ("common", "common"),
    ("cim_", "common"),
    ("w_eq_", "consumable"),
]

# World pickup models for medkits, pills, throwables, and ammo packs.
CONSUMABLE_MODEL_STEMS: tuple[str, ...] = (
    "w_eq_adrenaline",
    "w_eq_bile_flask",
    "w_eq_defibrillator",
    "w_eq_defibrillator_no_paddles",
    "w_eq_defibrillator_paddles",
    "w_eq_explosive_ammopack",
    "w_eq_incendiary_ammopack",
    "w_eq_medkit",
    "w_eq_molotov",
    "w_eq_painpills",
    "w_eq_pipebomb",
)

# Materials under materials/ that belong to those pickups (and their viewmodels).
CONSUMABLE_MATERIAL_PREFIXES: tuple[str, ...] = (
    "models/w_models/eq_adrenaline/",
    "models/w_models/eq_ammopack/",
    "models/w_models/eq_defibrillator/",
    "models/w_models/eq_medkit/",
    "models/w_models/eq_molotov/",
    "models/w_models/eq_painpills/",
    "models/w_models/eq_pipebomb/",
    "models/v_models/weapons/eq_adrenaline/",
    "models/v_models/weapons/eq_ammopack/",
    "models/v_models/weapons/eq_bile_flask/",
    "models/v_models/weapons/eq_defibrillator/",
    "models/v_models/weapons/eq_medkit/",
    "models/v_models/weapons/eq_molotov/",
    "models/v_models/weapons/eq_painpills/",
    "models/v_models/weapons/eq_pipebomb/",
    "models/props/terror/explosive_ammopack",
    "models/props/terror/incendiary_ammopack",
    "models/props/terror/exploding_ammo",
    "models/props/terror/incendiary_ammo",
)

# Flat render flags stamped onto every generated infected VMT.
# L4D2's infected shader is VertexLitGeneric. It recolors each common from a
# clothing gradient and from the entity color. Those knobs exist only on this
# shader: UnlitGeneric ignores them, which is why commons stayed red, blue,
# and black. Self-illumination is what keeps them from going dim in shadow.
# A lightwarp only remaps the lambert term, then still multiplies by the
# room's light, which is why indoor infected turned dark.
RENDER_FLAGS: dict[str, str] = {
    "$model": "1",
    "$ignorez": "1",
    "$nocull": "1",
    "$nofog": "1",
    "$nodecal": "1",
    "$halflambert": "0",
    "$phong": "0",
    "$ambientocclusion": "0",
    "$shinyblood": "0",
    "$burning": "0",
    "$wounded": "0",
    "$eyeglow": "0",
    "$disablevariation": "1",
    "$allowdiffusemodulation": "0",
    "$blendtintbybasealpha": "0",
    "$basecolortint": "[1 1 1]",
    "$selfillum": "1",
    "$selfillumfresnel": "0",
    "$selfillumtint": "[1 1 1]",
    "$selfillummask": f"{FLAT_MATERIAL_DIR}/flat_lightwarp",
}

LIGHTWARP_COLOR: tuple[int, int, int] = (255, 255, 255)

# Bullet streaks the client already draws. Recolouring them is what shows a
# shot on a public server. The listen-server script cannot run there.
TRACER_MATERIALS: tuple[str, ...] = (
    "particle/particle_glow_05_additive",
    "sprites/laserbeam",
)

# Client settings. Written to the game's cfg folder on deploy, then exec'd
# from autoexec, so they apply on any server. Server cvars are not in here.
CLIENT_COMMANDS: tuple[tuple[str, str], ...] = (
    ("r_drawtracers", "1"),
    ("r_drawtracers_firstperson", "1"),
    ("z_do_tracers", "1"),
    ("z_tracer_spacing", "1"),
    ("mat_hdr_level", "0"),
    ("mat_bloomscale", "0"),
    ("mat_disable_bloom", "1"),
    ("mat_colorcorrection", "0"),
    ("mat_motion_blur_enabled", "0"),
    ("mat_grain_scale_override", "0"),
    ("mat_antialias", "0"),
    ("mat_software_aa_strength", "0"),
    ("mat_specular", "0"),
    ("r_dynamic", "0"),
    ("muzzleflash_light", "0"),
    ("r_drawviewmodel", "0"),
    ("cl_drawhud", "0"),
    ("net_graph", "0"),
)

# Materials that must keep their alpha cutout instead of becoming solid quads.
# Relative to materials/, forward slashes, lowercase, no extension.
ALPHA_PRESERVE: set[str] = {
    "models/infected/boomer/boomer_hair",
    "models/infected/smoker/boomer_hair",
    "models/infected/witch/witch_hair",
}
ADDITIVE_PRESERVE: set[str] = {
    "models/infected/common/l4d2/cim_ceda_faceplate",
}

# Spitter ground bile. These particle materials are referenced only by
# particles/spitter_fx.pcf, so giving them $ignorez does not x-ray rain,
# blood or weapon effects. The flat green disc is pool_01_oriented; the
# others are its refraction, splash, foam and the slime spots it leaves.
SPITTER_PUDDLE_MATERIALS: tuple[str, ...] = (
    "particle/pool_01_oriented",
    "particle/warp_pool_01",
    "particle/water_splash/water_splash_add_nodepth",
    "particle/water_splash/water_splash_addself_nodepth",
    "particle/droplets/droplets_oriented_add_nodepth",
)

# The tongue that flies out and can be shot is a rope plus a joint sprite.
# smoker.mdl does not reference them, so the body override never reaches them.
SMOKER_TONGUE_MATERIALS: tuple[str, ...] = (
    "particle/smoker_tongue_beam",
    "particle/smoker_tongue_joint",
)


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
