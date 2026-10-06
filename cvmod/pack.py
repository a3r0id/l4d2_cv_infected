"""Package the build tree into an addon VPK and deploy it into the game."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import config

ADDONINFO = """\
"AddonInfo"
{
	addontitle			"CV Infected Override"
	addonversion		"1.0"
	addontagline		"Flat x-ray infected for computer vision"
	addonauthor			"cvmod pipeline"
	addondescription	"Replaces every infected material with a flat, unlit, depth-ignoring colour, one per infected class, so frames can be segmented by exact pixel colour. Survivors, weapons and world geometry are untouched."

	addonContent_Skin			1
	addonContent_CommonInfected	1
	addonContent_BossInfected	1
}
"""


def write_addoninfo(root: Path) -> Path:
    path = root / "addoninfo.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ADDONINFO, encoding="utf-8")
    return path


def _staging() -> Path:
    """vpk.exe names the archive after the folder, so stage under the addon name."""
    staging = config.WORK / "vpk" / config.ADDON_NAME
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for child in sorted(config.BUILD.iterdir()):
        target = staging / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)
    write_addoninfo(staging)
    return staging


def build_vpk() -> Path:
    if not config.BUILD.exists():
        raise FileNotFoundError(f"nothing to pack: {config.BUILD} does not exist")

    staging = _staging()
    produced = staging.parent / f"{config.ADDON_NAME}.vpk"
    if produced.exists():
        produced.unlink()

    result = subprocess.run(
        [str(config.VPK_EXE), str(staging)],
        capture_output=True,
        text=True,
        cwd=str(staging.parent),
    )
    if not produced.exists():
        raise RuntimeError(
            f"vpk.exe did not produce {produced}\n"
            f"exit={result.returncode}\n{result.stdout}\n{result.stderr}"
        )

    config.DIST.mkdir(parents=True, exist_ok=True)
    if config.VPK_PATH.exists():
        config.VPK_PATH.unlink()
    shutil.move(str(produced), str(config.VPK_PATH))
    shutil.rmtree(staging, ignore_errors=True)
    return config.VPK_PATH


def deploy(loose: bool = False) -> list[Path]:
    """Install into left4dead2/addons/.

    The VPK and the unpacked folder are mutually exclusive: shipping both would
    mount the same files twice, so deploying one removes the other.
    """
    config.ADDONS_DIR.mkdir(parents=True, exist_ok=True)
    vpk_target = config.ADDONS_DIR / f"{config.ADDON_NAME}.vpk"
    dir_target = config.ADDONS_DIR / config.ADDON_NAME
    written: list[Path] = []

    if loose:
        if vpk_target.exists():
            vpk_target.unlink()
        if dir_target.exists():
            shutil.rmtree(dir_target)
        shutil.copytree(config.BUILD, dir_target)
        write_addoninfo(dir_target)
        written.append(dir_target)
    else:
        if not config.VPK_PATH.exists():
            build_vpk()
        if dir_target.exists():
            shutil.rmtree(dir_target)
        try:
            shutil.copy2(config.VPK_PATH, vpk_target)
        except PermissionError as exc:
            raise PermissionError(
                f"{vpk_target} is in use, usually because Left 4 Dead 2 is running. "
                f"Close the game and deploy again. The built addon is at {config.VPK_PATH}."
            ) from exc
        written.append(vpk_target)

    return written


GAMEINFO = """\
"GameInfo"
{{
	game	"L4D2 CV verify"
	type multiplayer_only
	nomodels 1
	nohimodel 1
	nodegraph 0
	perfwizard 0
	SupportsDX8 0
	GameData	"left4dead2.fgd"

	FileSystem
	{{
		SteamAppId				550
		ToolsAppId				563

		// Search paths resolve against the directory holding left4dead2.exe.
		// The build tree goes first so its materials win over the stock ones,
		// which is what the addon does at runtime.
		SearchPaths
		{{
			Game				{build}
			Game				update
			Game				left4dead2_dlc3
			Game				left4dead2_dlc2
			Game				left4dead2_dlc1
			Game				left4dead2
			Game				hl2
		}}
	}}
}}
"""


def verify_gamedir() -> Path:
    """A throwaway mod directory that mounts build/ ahead of the stock game.

    HLMV does not mount addons/, so this is how the generated materials get
    seen by the model viewer.
    """
    gamedir = config.WORK / "verify_game"
    gamedir.mkdir(parents=True, exist_ok=True)
    (gamedir / "gameinfo.txt").write_text(
        GAMEINFO.format(build=config.search_path(config.BUILD)), encoding="utf-8"
    )
    return gamedir


def find_model(name: str) -> Path | None:
    for root, pattern in (
        (config.BUILD, f"models/**/{name}*.mdl"),
        (config.SRC_INFECTED_MODELS, f"**/{name}*.mdl"),
    ):
        matches = sorted(root.glob(pattern))
        exact = [m for m in matches if m.stem.lower() == name.lower()]
        if exact:
            return exact[0]
        if matches:
            return matches[0]
    return None


def open_hlmv(name: str, wait: bool = False) -> int:
    """Launch HLMV on a built proxy model, falling back to the stock model."""
    target = find_model(name)
    if target is None:
        print(f"no model matching {name!r} in build/ or {config.SRC_INFECTED_MODELS}")
        return 1

    gamedir = verify_gamedir()
    print(f"opening {target}")
    args = [str(config.HLMV), "-game", str(gamedir), str(target)]
    if wait:
        subprocess.run(args, env=config.studiomdl_env())
    else:
        subprocess.Popen(args, env=config.studiomdl_env())
    return 0
