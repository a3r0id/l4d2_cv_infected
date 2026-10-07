"""Package the build tree into an addon VPK and deploy it into the game."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import config, features as features_mod
from .features import Features

CLIENT_EXEC_LINE = "exec cv_client"
CLIENT_CFG_NAME = "cv_client.cfg"


def addoninfo_text(features: Features) -> str:
    parts = ["infected"]
    if features.consumables:
        parts.append("consumables")
    if features.trace:
        parts.append("trace")
    tag = ", ".join(parts)
    desc = (
        "Replaces infected materials with flat, depth-ignoring colours for computer vision."
    )
    if features.consumables:
        desc += " Medkits and other pickups are bright white."
    if features.trace:
        desc += " Includes cheat-only shot tracers and capture settings."
    weapon = "1" if features.consumables else "0"
    return f"""\
"AddonInfo"
{{
	addontitle			"CV Infected Override"
	addonversion		"1.6"
	addontagline		"Flat x-ray overrides ({tag})"
	addonauthor			"cvmod pipeline"
	addondescription	"{desc}"

	addonContent_Skin			1
	addonContent_CommonInfected	1
	addonContent_BossInfected	1
	addonContent_Weapon			{weapon}
}}
"""


def write_addoninfo(root: Path, features: Features) -> Path:
    path = root / "addoninfo.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(addoninfo_text(features), encoding="utf-8")
    return path


def stage_addon(features: Features) -> Path:
    """Copy the selected build files into a clean staging folder for packing."""
    if not config.BUILD.exists():
        raise FileNotFoundError(f"nothing to pack: {config.BUILD} does not exist")

    staging = config.WORK / "vpk" / config.ADDON_NAME
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    copied = 0
    for path in sorted(config.BUILD.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(config.BUILD).as_posix()
        if not features_mod.include_build_path(rel, features):
            continue
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied += 1

    write_addoninfo(staging, features)
    (staging / "cv_features.txt").write_text(features.label() + "\n", encoding="utf-8")
    if copied == 0:
        raise RuntimeError("staging copied zero files; build tree may be empty")
    return staging


def build_vpk(features: Features | None = None) -> Path:
    features = features or Features()
    staging = stage_addon(features)
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


def deploy(loose: bool = False, features: Features | None = None) -> list[Path]:
    """Install into left4dead2/addons/, replacing any previous install.

    Optional cfg hooks from a prior --feat-trace install are removed when that
    feature is off, so each deploy is a clean slate for the selected features.
    """
    features = features or Features()
    config.ADDONS_DIR.mkdir(parents=True, exist_ok=True)
    vpk_target = config.ADDONS_DIR / f"{config.ADDON_NAME}.vpk"
    dir_target = config.ADDONS_DIR / config.ADDON_NAME
    written: list[Path] = []

    # Always clear both install shapes first so a VPK never sits next to a
    # leftover loose folder from the last deploy.
    if vpk_target.exists():
        try:
            vpk_target.unlink()
        except PermissionError as exc:
            raise PermissionError(
                f"{vpk_target} is in use, usually because Left 4 Dead 2 is running. "
                f"Close the game and deploy again. The built addon is at {config.VPK_PATH}."
            ) from exc
    if dir_target.exists():
        shutil.rmtree(dir_target)

    if loose:
        staging = stage_addon(features)
        shutil.copytree(staging, dir_target)
        shutil.rmtree(staging, ignore_errors=True)
        written.append(dir_target)
    else:
        build_vpk(features)
        try:
            shutil.copy2(config.VPK_PATH, vpk_target)
        except PermissionError as exc:
            raise PermissionError(
                f"{vpk_target} is in use, usually because Left 4 Dead 2 is running. "
                f"Close the game and deploy again. The built addon is at {config.VPK_PATH}."
            ) from exc
        written.append(vpk_target)

    installed, cleaned = sync_client_cfg(features)
    written.extend(installed)
    for path in cleaned:
        print(f"cleaned {path}")
    return written


def _strip_exec_line(path: Path, line: str) -> bool:
    """Remove exact `line` entries from a cfg. Returns True when the file changed."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip() != line]
    new_text = ("\n".join(lines) + "\n") if lines else ""
    if new_text == text:
        return False
    if new_text:
        path.write_text(new_text, encoding="utf-8")
    else:
        path.unlink()
    return True


def sync_client_cfg(features: Features) -> tuple[list[Path], list[Path]]:
    """Install or remove the loose client cfg hooks for --feat-trace.

    Returns `(installed, cleaned)`.
    """
    cfg_dir = config.GAME_DIR / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / CLIENT_CFG_NAME
    autoexec = cfg_dir / "autoexec.cfg"
    valve = cfg_dir / "valve.rc"
    installed: list[Path] = []
    cleaned: list[Path] = []

    if not features.trace:
        if path.exists():
            path.unlink()
            cleaned.append(path)
        if _strip_exec_line(autoexec, CLIENT_EXEC_LINE):
            cleaned.append(autoexec)
        if _strip_exec_line(valve, CLIENT_EXEC_LINE):
            cleaned.append(valve)
        return installed, cleaned

    body = [
        "// cv_infected client settings. Applied from autoexec and valve.rc.",
        "// Installed only when packing with --feat-trace.",
        "",
    ]
    body.extend(f"{name} {value}" for name, value in config.CLIENT_COMMANDS)
    body.append("")
    body.append('echo "[cv_infected] client settings applied"')
    body.append("")
    path.write_text("\n".join(body), encoding="utf-8")
    installed.append(path)

    existing = autoexec.read_text(encoding="utf-8", errors="replace") if autoexec.exists() else ""
    if CLIENT_EXEC_LINE not in existing:
        suffix = "" if existing.endswith("\n") or not existing else "\n"
        autoexec.write_text(existing + suffix + CLIENT_EXEC_LINE + "\n", encoding="utf-8")
    installed.append(autoexec)

    valve_text = valve.read_text(encoding="utf-8", errors="replace") if valve.exists() else ""
    kept = [ln for ln in valve_text.splitlines() if ln.strip() != CLIENT_EXEC_LINE]
    if not kept:
        kept = ["exec joystick.cfg", "exec autoexec.cfg", "stuffcmds"]
    while kept and not kept[-1].strip():
        kept.pop()
    kept.append(CLIENT_EXEC_LINE)
    valve.write_text("\n".join(kept) + "\n", encoding="utf-8")
    installed.append(valve)
    return installed, removed


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
