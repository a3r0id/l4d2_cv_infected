"""Driver for studiomdl.

studiomdl writes its output under the directory passed to -game, so it is
pointed at a scratch mod folder whose gameinfo search-paths the real game.
That keeps compiled files out of the game install while still letting
studiomdl resolve `$includemodel` against the stock animation models.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config

GAMEINFO = """\
"GameInfo"
{{
	game	"L4D2 CV compile"
	type multiplayer_only
	nomodels 1
	nohimodel 1
	nodegraph 0
	SupportsDX8 0

	FileSystem
	{{
		SteamAppId				550
		ToolsAppId				563

		// Relative entries resolve against the folder holding left4dead2.exe.
		SearchPaths
		{{
			Game				|gameinfo_path|.
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

MODEL_SUFFIXES = (".mdl", ".vvd", ".vtx", ".dx90.vtx", ".dx80.vtx", ".sw.vtx", ".phy", ".ani")

PHY_CHECKSUM_OFFSET = 12


@dataclass
class CompileResult:
    ok: bool
    outputs: list[Path]
    log: str
    command: list[str]


def scratch_gamedir() -> Path:
    gamedir = config.WORK / "compile"
    gamedir.mkdir(parents=True, exist_ok=True)
    (gamedir / "gameinfo.txt").write_text(
        GAMEINFO.format(build=config.search_path(config.BUILD)), encoding="utf-8"
    )
    return gamedir


def run(qc_path: Path) -> CompileResult:
    gamedir = scratch_gamedir()
    command = [
        str(config.STUDIOMDL),
        "-game",
        str(gamedir),
        "-nop4",
        "-nowarnings",
        str(qc_path),
    ]
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(qc_path.parent),
        env=config.studiomdl_env(),
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    return CompileResult(ok=proc.returncode == 0, outputs=[], log=log, command=command)


def collect(gamedir: Path, model_rel: str, dest_root: Path) -> list[Path]:
    """Move compiled files for `model_rel` (e.g. infected/hunter.mdl) into the build tree."""
    src_dir = gamedir / "models" / Path(model_rel).parent
    stem = Path(model_rel).stem
    dest_dir = dest_root / "models" / Path(model_rel).parent
    dest_dir.mkdir(parents=True, exist_ok=True)

    moved: list[Path] = []
    if not src_dir.exists():
        return moved
    for src in sorted(src_dir.iterdir()):
        if not src.is_file():
            continue
        name = src.name
        if not name.lower().startswith(stem.lower() + "."):
            continue
        if not name.lower().endswith(MODEL_SUFFIXES):
            continue
        dest = dest_dir / name
        shutil.move(str(src), str(dest))
        moved.append(dest)
    return moved


def mdl_checksum(path: Path) -> int:
    with path.open("rb") as fh:
        return struct.unpack("<i", fh.read(12)[8:12])[0]


def copy_phy(source_mdl: Path, built_mdl: Path) -> Path | None:
    """Reuse the stock collision mesh, repointed at the new model.

    The .phy references bones by name in its trailing keyvalues block, so it
    stays valid as long as the skeleton is unchanged. Only the checksum, which
    the engine matches against the .mdl, has to be rewritten.
    """
    source_phy = source_mdl.with_suffix(".phy")
    if not source_phy.exists():
        return None
    data = bytearray(source_phy.read_bytes())
    if len(data) < PHY_CHECKSUM_OFFSET + 4:
        return None
    struct.pack_into("<i", data, PHY_CHECKSUM_OFFSET, mdl_checksum(built_mdl))
    dest = built_mdl.with_suffix(".phy")
    dest.write_bytes(bytes(data))
    return dest
