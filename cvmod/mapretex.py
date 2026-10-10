"""Flatten world materials listed in config.json `map_materials_batch_retextures`.

Each `dir` is a folder inside the game VPK (`pak01://materials/buildings`).
Every VMT in that folder is rewritten to an unlit material whose `$basetexture`
is the PNG named by `replace`. Props, models, and other material folders are
left alone.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from . import config, manifest, vpkutil, vtf

GENERATOR_VERSION = "1"
_MAX_SIZE = 256


def _texture_ref(png_rel: str) -> str:
    stem = Path(png_rel).stem.lower().replace(" ", "_")
    return f"{config.FLAT_MATERIAL_DIR}/map_{stem}"


def _encode_png(path: Path) -> bytes:
    image = Image.open(path).convert("RGBA")
    colors = image.getcolors(maxcolors=2)
    if colors is not None and len(colors) == 1:
        red, green, blue, alpha = colors[0][1]
        return vtf.build((red, green, blue), alpha=alpha, size=16)
    side = max(image.size)
    power = 1
    while power < side and power < _MAX_SIZE:
        power *= 2
    if image.size != (power, power):
        image = image.resize((power, power), Image.Resampling.BOX)
    return vtf.build_image(np.asarray(image, dtype=np.uint8))


def _vmt(texture_ref: str) -> str:
    return (
        "UnlitGeneric\n"
        "{\n"
        f'\t$basetexture "{texture_ref}"\n'
        '\t$nocull      "1"\n'
        '\t$nofog       "1"\n'
        '\t$nodecal     "1"\n'
        '\t$ignorez     "0"\n'
        "}\n"
    )


def _material_keys(prefix: str) -> list[str]:
    """VMT paths under materials/, without the extension."""
    root = f"materials/{prefix.strip('/')}/".lower()
    keys: list[str] = []
    for rel in vpkutil.index_game_pak():
        if rel.startswith(root) and rel.endswith(".vmt"):
            keys.append(rel[len("materials/") : -len(".vmt")])
    return sorted(keys)


def write(mani: manifest.Manifest, force: bool = False) -> tuple[int, int, int]:
    """Write map replacement materials. Returns (written, skipped, failed)."""
    written = skipped = failed = 0
    out_materials = config.BUILD / "materials"
    textures: dict[str, str] = {}

    for prefix, png_rel in config.MAP_RETEXTURES:
        png = config.HELPERS / png_rel
        ref = _texture_ref(png_rel)
        if ref not in textures:
            if not png.is_file():
                print(f"map retex: missing {png}")
                failed += 1
                continue
            try:
                data = _encode_png(png)
            except (OSError, ValueError) as exc:
                print(f"map retex: {png}: {exc}")
                failed += 1
                continue
            dest = out_materials / f"{ref}.vtf"
            unit = f"materials/_map/{Path(ref).name}"
            key = manifest.sha(GENERATOR_VERSION, ref, manifest.file_sha(png), data)
            if not force and mani.is_current(unit, key) and dest.exists():
                mani.touch(unit)
                skipped += 1
            else:
                manifest.write_if_changed(dest, data)
                mani.record(unit, key, [dest])
                written += 1
            textures[ref] = ref

        if ref not in textures:
            continue
        body = _vmt(ref).encode("utf-8")
        for material_key in _material_keys(prefix):
            unit = f"materials/{material_key}"
            unit_key = manifest.sha(GENERATOR_VERSION, "map-retex", ref, body)
            dest = out_materials / f"{material_key}.vmt"
            if not force and mani.is_current(unit, unit_key) and dest.exists():
                mani.touch(unit)
                skipped += 1
                continue
            manifest.write_if_changed(dest, body)
            mani.record(unit, unit_key, [dest])
            written += 1

    return written, skipped, failed
