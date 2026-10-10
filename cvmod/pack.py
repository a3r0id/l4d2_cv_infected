"""Package the build tree into an addon VPK and deploy it into the game."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import config, features as features_mod
from .features import Features

CLIENT_EXEC_LINE = "exec cv_client"
CLIENT_CFG_NAME = "cv_client.cfg"
CLEANUP_EXEC_LINE = "exec cv_cleanup"
CLEANUP_CFG_NAME = "cv_cleanup.cfg"
CLEANUP_RESTORE_EXEC_LINE = "exec cv_cleanup_restore"
CLEANUP_RESTORE_CFG_NAME = "cv_cleanup_restore.cfg"


def addoninfo_text(features: Features) -> str:
    parts = ["infected"]
    if features.hitbox_models:
        parts.append("hitboxes")
    if features.consumables:
        parts.append("consumables")
    if features.trace:
        parts.append("trace")
    if features.cleanup:
        parts.append("cleanup")
    if features.sounds:
        parts.append("sounds")
    if features.map_retex:
        parts.append("mapretex")
    tag = ", ".join(parts)
    desc = (
        "Replaces infected materials with flat, depth-ignoring colours for computer vision."
    )
    if features.hitbox_models:
        desc += " Replaces infected meshes with hitbox proxy models."
    if features.consumables:
        desc += " Pickups are x-rayed; explosive ammo packs are bright gold."
    if features.trace:
        desc += " Includes cheat-only shot tracers and capture settings."
    if features.cleanup:
        desc += " Caps ragdolls/decals; C clears clutter."
    if features.sounds:
        desc += " Ships custom sound replacements."
    if features.map_retex:
        desc += " Flattens selected world materials to a single texture."
    weapon = "1" if features.consumables else "0"
    return f"""\
"AddonInfo"
{{
	addontitle			"CV Infected Override"
	addonversion		"1.8"
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

    Optional cfg hooks and custom sounds from prior feature installs are removed
    when those features are off, so each deploy is a clean slate.
    """
    from . import sounds

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

    installed, cleaned = sync_loose_cfgs(features)
    written.extend(installed)
    for path in cleaned:
        print(f"cleaned {path}")

    sound_installed, sound_cleaned = sounds.sync(features.sounds)
    written.extend(sound_installed)
    for path in sound_cleaned:
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


def _ensure_exec_line(path: Path, line: str) -> bool:
    """Append `line` when missing. Returns True when the file changed."""
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if line in existing:
        return False
    suffix = "" if existing.endswith("\n") or not existing else "\n"
    path.write_text(existing + suffix + line + "\n", encoding="utf-8")
    return True


def _ensure_valve_exec(valve: Path, line: str) -> None:
    """Append `line` after stuffcmds so it wins over launch-option binds."""
    valve_text = valve.read_text(encoding="utf-8", errors="replace") if valve.exists() else ""
    kept = [ln for ln in valve_text.splitlines() if ln.strip() != line]
    if not kept:
        kept = ["exec joystick.cfg", "exec autoexec.cfg", "stuffcmds"]
    while kept and not kept[-1].strip():
        kept.pop()
    kept.append(line)
    valve.write_text("\n".join(kept) + "\n", encoding="utf-8")


def _cleanup_restore_body() -> str:
    """Put stock binds back when --feat-cleanup is removed."""
    return "\n".join(
        [
            "// cv_infected cleanup uninstall. Restores stock binds.",
            'bind "MOUSE1" "+attack"',
            'bind "MOUSE3" "+zoom"',
            'bind "c" "+voicerecord"',
            'echo "[cv_infected] shot cleanup removed"',
            "",
        ]
    )


def _restore_cleanup_binds(cfg_dir: Path) -> list[Path]:
    """Restore stock binds after removing --feat-cleanup."""
    touched: list[Path] = []
    restore_path = cfg_dir / CLEANUP_RESTORE_CFG_NAME
    restore_path.write_text(_cleanup_restore_body(), encoding="utf-8")
    touched.append(restore_path)

    # Persist into config.cfg so the next launch keeps stock binds even if the
    # one-shot restore cfg is not exec'd again.
    config_cfg = cfg_dir / "config.cfg"
    if config_cfg.exists():
        text = config_cfg.read_text(encoding="utf-8", errors="replace")
        new_text, n1 = re.subn(
            r'(?im)^(\s*bind\s+"MOUSE1"\s+)"[^"]*"',
            r'\1"+attack"',
            text,
        )
        new_text, n3 = re.subn(
            r'(?im)^(\s*bind\s+"MOUSE3"\s+)"[^"]*"',
            r'\1"+zoom"',
            new_text,
        )
        new_text, nc = re.subn(
            r'(?im)^(\s*bind\s+"c"\s+)"[^"]*"',
            r'\1"+voicerecord"',
            new_text,
        )
        if n1 or n3 or nc:
            config_cfg.write_text(new_text, encoding="utf-8")
            touched.append(config_cfg)

    autoexec = cfg_dir / "autoexec.cfg"
    if _ensure_exec_line(autoexec, CLEANUP_RESTORE_EXEC_LINE):
        touched.append(autoexec)
    return touched


def _cleanup_cfg_body() -> str:
    """Clear clutter without breaking the Fire key glyph.

    L4D2's "Press [key] to play as ..." looks up which key is bound to the
    exact command `+attack`. Binding MOUSE1 to an alias (`+cv_attack`) or to
    `+attack; cl_cleanup` makes that lookup fail and shows [?].

    Keep MOUSE1 bound to the exact string `+attack`. Clutter is limited by the
    cleanup cvars; C runs an on-demand clear. Do not alias `+attack` itself —
    that recurses and can hang the client.
    """
    lines = [
        "// cv_infected shot cleanup. Installed with --feat-cleanup.",
        "// Caps keep ragdolls/decals sparse. C clears on demand.",
        "// MOUSE1 must stay bound to the exact string +attack so takeover UI",
        '// can show "Press [MOUSE1] to play as ..." instead of [?].',
        "",
    ]
    lines.extend(f"{name} {value}" for name, value in config.CLEANUP_COMMANDS)
    lines.extend(
        [
            "",
            'alias "cl_cleanup" "r_cleardecals; cl_destroy_ragdolls"',
            # Drop any previous wrap that stole the Fire glyph.
            'alias "+cv_attack" "+attack"',
            'alias "-cv_attack" "-attack"',
            'bind "MOUSE1" "+attack"',
            # Scope stays on MOUSE3; C is unused for most players (stock: voice).
            'bind "MOUSE3" "+zoom"',
            'bind "c" "cl_cleanup"',
            "cl_cleanup",
            "",
            'echo "[cv_infected] shot cleanup applied"',
            "",
        ]
    )
    return "\n".join(lines)


def sync_loose_cfgs(features: Features) -> tuple[list[Path], list[Path]]:
    """Install or remove loose cfg hooks for --feat-trace / --feat-cleanup.

    Returns `(installed, cleaned)`.
    """
    cfg_dir = config.GAME_DIR / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    autoexec = cfg_dir / "autoexec.cfg"
    valve = cfg_dir / "valve.rc"
    installed: list[Path] = []
    cleaned: list[Path] = []

    client_path = cfg_dir / CLIENT_CFG_NAME
    if features.trace:
        body = [
            "// cv_infected client settings. Applied from autoexec and valve.rc.",
            "// Installed only when packing with --feat-trace.",
            "",
        ]
        body.extend(f"{name} {value}" for name, value in config.CLIENT_COMMANDS)
        body.append("")
        body.append('echo "[cv_infected] client settings applied"')
        body.append("")
        client_path.write_text("\n".join(body), encoding="utf-8")
        installed.append(client_path)
        _ensure_exec_line(autoexec, CLIENT_EXEC_LINE)
        installed.append(autoexec)
        _ensure_valve_exec(valve, CLIENT_EXEC_LINE)
        installed.append(valve)
    else:
        if client_path.exists():
            client_path.unlink()
            cleaned.append(client_path)
        if _strip_exec_line(autoexec, CLIENT_EXEC_LINE):
            cleaned.append(autoexec)
        if _strip_exec_line(valve, CLIENT_EXEC_LINE):
            cleaned.append(valve)

    cleanup_path = cfg_dir / CLEANUP_CFG_NAME
    restore_path = cfg_dir / CLEANUP_RESTORE_CFG_NAME
    if features.cleanup:
        cleanup_path.write_text(_cleanup_cfg_body(), encoding="utf-8")
        installed.append(cleanup_path)
        _ensure_exec_line(autoexec, CLEANUP_EXEC_LINE)
        if _strip_exec_line(autoexec, CLEANUP_RESTORE_EXEC_LINE):
            pass
        if autoexec not in installed:
            installed.append(autoexec)
        # After stuffcmds so launch options cannot steal MOUSE1 back.
        _ensure_valve_exec(valve, CLEANUP_EXEC_LINE)
        if valve not in installed:
            installed.append(valve)
        if restore_path.exists():
            restore_path.unlink()
            cleaned.append(restore_path)
    else:
        if cleanup_path.exists():
            cleanup_path.unlink()
            cleaned.append(cleanup_path)
        if _strip_exec_line(autoexec, CLEANUP_EXEC_LINE):
            if autoexec not in cleaned:
                cleaned.append(autoexec)
        if _strip_exec_line(valve, CLEANUP_EXEC_LINE):
            if valve not in cleaned:
                cleaned.append(valve)
        for path in _restore_cleanup_binds(cfg_dir):
            cleaned.append(path)

    return installed, cleaned


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
