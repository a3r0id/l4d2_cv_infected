"""Phase 1: replace every infected material with a flat, unlit, x-ray colour.

The colour is baked into the texture rather than applied with `$color2`, so the
value that lands in the framebuffer is the authored RGB and mask extraction is
an exact-match test. Materials whose base texture carries real transparency
(hair cards) get a generated texture that keeps the original alpha and replaces
only the colour, so cutouts do not become solid quads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import config, index as index_mod, manifest, vmt, vtf

# Bump when the emitted VMT/VTF layout changes, to force a rebuild.
GENERATOR_VERSION = "3"

TRANSPARENT_THRESHOLD = 0.001  # fraction of texels below alpha 128


@dataclass
class Result:
    stats: manifest.Stats = field(default_factory=manifest.Stats)
    masked: list[str] = field(default_factory=list)
    skipped_opaque: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"materials: {self.stats}"]
        if self.masked:
            lines.append(f"  alpha-masked textures ({len(self.masked)}): {', '.join(sorted(self.masked))}")
        if self.skipped_opaque:
            lines.append(
                f"  declared alpha but fully opaque, flattened ({len(self.skipped_opaque)}): "
                f"{', '.join(sorted(self.skipped_opaque))}"
            )
        for key, err in self.errors:
            lines.append(f"  ERROR {key}: {err}")
        return "\n".join(lines)


def flat_texture_ref(cls: str) -> str:
    return f"{config.FLAT_MATERIAL_DIR}/flat_{cls}"


def mask_texture_ref(key: str) -> str:
    stem = key.replace("models/infected/", "").replace("/", "_")
    return f"{config.FLAT_MATERIAL_DIR}/mask_{stem}"


def _source_texture(entry: index_mod.MaterialEntry) -> Path | None:
    """Locate the .vtf behind a material's $basetexture."""
    if not entry.basetexture:
        return None
    rel = entry.basetexture.replace("\\", "/").strip().strip('"')
    path = config.SRC_MATERIALS / f"{rel}.vtf"
    if path.exists():
        return path
    # Case differences between the VMT and what is on disk.
    parent = path.parent
    if parent.exists():
        target = path.name.lower()
        for candidate in parent.iterdir():
            if candidate.name.lower() == target:
                return candidate
    return None


def _alpha_mask(entry: index_mod.MaterialEntry):
    """Return the alpha channel if the texture is genuinely see-through."""
    if not (entry.alphatest or entry.translucent):
        return None
    source = _source_texture(entry)
    if source is None:
        return None
    alpha = vtf.read_alpha(source)
    if float((alpha < 128).mean()) < TRANSPARENT_THRESHOLD:
        return None
    return alpha


def _vmt_params(entry: index_mod.MaterialEntry, texture_ref: str, masked: bool) -> dict[str, str]:
    params: dict[str, str] = {"$basetexture": texture_ref}
    params.update(config.RENDER_FLAGS)
    if masked:
        params["$alphatest"] = "1"
        params["$allowalphatocoverage"] = "0"
    if entry.additive:
        params["$additive"] = "1"
    if entry.translucent and not masked:
        params["$translucent"] = "1"
    return params


def build(
    idx: index_mod.Index,
    mani: manifest.Manifest,
    force: bool = False,
    only: str | None = None,
) -> Result:
    result = Result()
    out_materials = config.BUILD / "materials"

    used_classes = sorted({e.cls for e in idx.materials.values()} | set(config.CLASS_COLORS))

    # Shared flat texture plus the material the phase 2 proxy meshes point at,
    # one pair per class.
    for cls in used_classes:
        color = config.CLASS_COLORS.get(cls, (255, 255, 255))
        texture = out_materials / f"{flat_texture_ref(cls)}.vtf"
        proxy_vmt = out_materials / f"{config.FLAT_MATERIAL_DIR}/proxy_{cls}.vmt"
        unit = f"materials/_flat/{cls}"

        data = vtf.build(color)
        proxy_text = _render_vmt(
            {"$basetexture": flat_texture_ref(cls), **config.RENDER_FLAGS}
        )
        key = manifest.sha(GENERATOR_VERSION, repr(color), data, proxy_text)
        if not force and mani.is_current(unit, key) and texture.exists() and proxy_vmt.exists():
            mani.touch(unit)
            result.stats.skipped += 1
            continue
        manifest.write_if_changed(texture, data)
        manifest.write_if_changed(proxy_vmt, proxy_text.encode("utf-8"))
        mani.record(unit, key, [texture, proxy_vmt])
        result.stats.written += 1

    for key_name, entry in sorted(idx.materials.items()):
        if only and only.lower() not in key_name.lower():
            continue
        unit = f"materials/{key_name}"
        color = config.CLASS_COLORS.get(entry.cls, (255, 255, 255))
        outputs: list[Path] = []

        try:
            alpha = _alpha_mask(entry)
        except (vtf.VtfError, OSError) as exc:
            result.errors.append((key_name, str(exc)))
            result.stats.failed += 1
            alpha = None

        if alpha is not None:
            texture_ref = mask_texture_ref(key_name)
            texture_data = vtf.build_masked(color, alpha)
            result.masked.append(key_name)
        else:
            texture_ref = flat_texture_ref(entry.cls)
            texture_data = None
            if entry.alphatest or entry.translucent:
                result.skipped_opaque.append(key_name)

        params = _vmt_params(entry, texture_ref, masked=alpha is not None)
        vmt_text = _render_vmt(params)
        unit_key = manifest.sha(
            GENERATOR_VERSION,
            vmt_text,
            repr(color),
            texture_data or b"",
        )

        vmt_path = out_materials / f"{key_name}.vmt"
        texture_path = out_materials / f"{texture_ref}.vtf" if texture_data else None

        if not force and mani.is_current(unit, unit_key):
            mani.touch(unit)
            result.stats.skipped += 1
            continue

        manifest.write_if_changed(vmt_path, vmt_text.encode("utf-8"))
        outputs.append(vmt_path)
        if texture_data and texture_path:
            manifest.write_if_changed(texture_path, texture_data)
            outputs.append(texture_path)

        mani.record(unit, unit_key, outputs)
        result.stats.written += 1

    if write_capture_cfg(mani, force=force):
        result.stats.written += 1
    else:
        result.stats.skipped += 1

    from . import shotlines

    if shotlines.write(mani, force=force):
        result.stats.written += 1
    else:
        result.stats.skipped += 1

    if not only:
        _write_spitter_puddle(mani, force, result)
    if not only or "smoker" in only.lower():
        _write_smoker_tongue(mani, force, result)
    if not only:
        _write_lightwarp(mani, force, result)
        _write_client_tracers(mani, force, result)

    if not only:
        # Must run after every unit above has been touched or recorded.
        removed = mani.prune("materials/")
        result.stats.removed = len(removed)

    return result


def _with_ignorez(text: str) -> tuple[str, dict[str, str]]:
    """Keep a particle material as-is and force it to draw through walls."""
    shader, body = vmt.parse_text(text)
    params: dict[str, str] = {}
    for key, value in body:
        if isinstance(value, list):
            raise vmt.VmtError(f"{shader} has a nested block")
        if key.lower() == "$ignorez":
            continue
        params[key] = value
    params["$ignorez"] = "1"
    return shader, params


def _write_spitter_puddle(mani: manifest.Manifest, force: bool, result: Result) -> None:
    out_materials = config.BUILD / "materials"
    for key in config.SPITTER_PUDDLE_MATERIALS:
        unit = f"materials/{key}"
        source = config.SRC_MATERIALS / f"{key}.vmt"
        if not source.exists():
            result.errors.append((key, "source vmt missing"))
            result.stats.failed += 1
            continue
        raw = source.read_text(encoding="utf-8", errors="replace")
        try:
            shader, params = _with_ignorez(raw)
        except vmt.VmtError as exc:
            result.errors.append((key, str(exc)))
            result.stats.failed += 1
            continue
        dest = out_materials / f"{key}.vmt"
        width = max((len(k) for k in params), default=0)
        lines = [shader, "{"]
        for name, value in params.items():
            shown = str(value)
            if not (shown.startswith('"') and shown.endswith('"')):
                shown = f'"{shown}"'
            lines.append(f"\t{name.ljust(width)} {shown}")
        lines.append("}")
        lines.append("")
        text = "\n".join(lines)
        data = text.encode("utf-8")
        unit_key = manifest.sha(GENERATOR_VERSION, "puddle-ignorez", data)
        if not force and mani.is_current(unit, unit_key) and dest.exists():
            mani.touch(unit)
            result.stats.skipped += 1
            continue
        manifest.write_if_changed(dest, data)
        mani.record(unit, unit_key, [dest])
        result.stats.written += 1


def _write_smoker_tongue(mani: manifest.Manifest, force: bool, result: Result) -> None:
    """Retint the tongue rope and joint to the smoker colour and draw them through walls.

    The shader has to stay Cable or SpriteCard. Those are what the rope and the
    joint sprite actually render with. Swapping in UnlitGeneric makes the tongue
    disappear.
    """
    out_materials = config.BUILD / "materials"
    texture = flat_texture_ref("smoker")
    drop = {
        "$bumpmap",
        "$phong",
        "$phongboost",
        "$halflambert",
        "$phongfresnelranges",
        "$ambientocclusion",
        "$diffuseexp",
        "$depthblend",
    }
    for key in config.SMOKER_TONGUE_MATERIALS:
        unit = f"materials/{key}"
        source = config.SRC_MATERIALS / f"{key}.vmt"
        if not source.exists():
            result.errors.append((key, "source vmt missing"))
            result.stats.failed += 1
            continue
        raw = source.read_text(encoding="utf-8", errors="replace")
        try:
            shader, body = vmt.parse_text(raw)
        except vmt.VmtError as exc:
            result.errors.append((key, str(exc)))
            result.stats.failed += 1
            continue
        params: dict[str, str] = {}
        for name, value in body:
            if isinstance(value, list):
                result.errors.append((key, f"{shader} has a nested block"))
                result.stats.failed += 1
                params = {}
                break
            lowered = name.lower()
            if lowered in drop:
                continue
            params[lowered] = value
        if not params and key not in (err for err, _ in result.errors):
            continue
        if any(err == key for err, _ in result.errors):
            continue
        params["$basetexture"] = texture
        params["$ignorez"] = "1"
        params["$nocull"] = "1"
        params["$nofog"] = "1"
        params["$vertexcolor"] = "0"
        params["$vertexalpha"] = "0"
        params["$translucent"] = "0"
        params["$allowdiffusemodulation"] = "0"
        dest = out_materials / f"{key}.vmt"
        width = max(len(name) for name in params)
        lines = [shader, "{"]
        for name, value in params.items():
            shown = str(value)
            if not (shown.startswith('"') and shown.endswith('"')):
                shown = f'"{shown}"'
            lines.append(f"\t{name.ljust(width)} {shown}")
        lines.append("}")
        lines.append("")
        data = "\n".join(lines).encode("utf-8")
        unit_key = manifest.sha(GENERATOR_VERSION, "smoker-tongue", data)
        if not force and mani.is_current(unit, unit_key) and dest.exists():
            mani.touch(unit)
            result.stats.skipped += 1
            continue
        manifest.write_if_changed(dest, data)
        mani.record(unit, unit_key, [dest])
        result.stats.written += 1


def _write_lightwarp(mani: manifest.Manifest, force: bool, result: Result) -> None:
    """White ramp so VertexLitGeneric's lighting term stays 1.

    The infected shader multiplies the texture by this lookup. Every texel is
    white, so a shaded pixel keeps the baked class color.
    """
    out_materials = config.BUILD / "materials"
    dest = out_materials / f"{config.FLAT_MATERIAL_DIR}/flat_lightwarp.vtf"
    data = vtf.build(config.LIGHTWARP_COLOR)
    unit = "materials/_flat/lightwarp"
    key = manifest.sha(GENERATOR_VERSION, "lightwarp", data)
    if not force and mani.is_current(unit, key) and dest.exists():
        mani.touch(unit)
        result.stats.skipped += 1
        return
    manifest.write_if_changed(dest, data)
    mani.record(unit, key, [dest])
    result.stats.written += 1


def _write_client_tracers(mani: manifest.Manifest, force: bool, result: Result) -> None:
    """Recolour the bullet streak the client draws for every server.

    `weapon_tracers` stretches particle/particle_glow_05_additive from the
    muzzle to the impact. sprites/laserbeam is the other streak material.
    Both have to stay sprite shaders or the particle renderer drops them.
    """
    out_materials = config.BUILD / "materials"
    texture = f"{config.FLAT_MATERIAL_DIR}/flat_tracer"
    bodies = {
        "particle/particle_glow_05_additive": (
            "SpriteCard",
            {
                "$basetexture": texture,
                "$additive": "1",
                "$translucent": "1",
                "$ignorez": "1",
                "$nocull": "1",
                "$nofog": "1",
                "$vertexcolor": "0",
                "$vertexalpha": "1",
                "$depthblend": "0",
            },
        ),
        "sprites/laserbeam": (
            "Sprite",
            {
                "$spriteorientation": "vp_parallel",
                "$spriteorigin": "[ 0.50 0.50 ]",
                "$basetexture": texture,
                "$additive": "1",
                "$translucent": "1",
                "$ignorez": "1",
                "$nocull": "1",
                "$nofog": "1",
                "$vertexcolor": "0",
                "$vertexalpha": "1",
            },
        ),
    }
    for key, (shader, params) in bodies.items():
        unit = f"materials/{key}"
        dest = out_materials / f"{key}.vmt"
        width = max(len(name) for name in params)
        lines = [shader, "{"]
        for name, value in params.items():
            lines.append(f'\t{name.ljust(width)} "{value}"')
        lines.append("}")
        lines.append("")
        data = "\n".join(lines).encode("utf-8")
        unit_key = manifest.sha(GENERATOR_VERSION, "client-tracer", data)
        if not force and mani.is_current(unit, unit_key) and dest.exists():
            mani.touch(unit)
            result.stats.skipped += 1
            continue
        manifest.write_if_changed(dest, data)
        mani.record(unit, unit_key, [dest])
        result.stats.written += 1


def _render_vmt(params: dict[str, str]) -> str:
    width = max(len(k) for k in params)
    lines = ["VertexLitGeneric", "{"]
    for key, value in params.items():
        lines.append(f'\t{key.ljust(width)} "{value}"')
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _capture_cfg() -> str:
    """Same commands the map script applies. Kept so the values are visible on disk."""
    lines = [
        "// Applied automatically when a map loads (scripts/vscripts/mapspawn_addon.nut).",
        "// exec cannot see this file inside an addon VPK.",
        "",
    ]
    lines.extend(f"{name} {value}" for name, value in config.CAPTURE_COMMANDS)
    lines.append("")
    lines.append('echo "[cv_infected] capture settings applied"')
    lines.append("")
    return "\n".join(lines)


def write_capture_cfg(mani: manifest.Manifest, force: bool = False) -> bool:
    out = config.BUILD / "cfg" / "cv_capture.cfg"
    data = _capture_cfg().encode("utf-8")
    key = manifest.sha(GENERATOR_VERSION, data)
    unit = "materials/_cfg/cv_capture"
    if not force and mani.is_current(unit, key) and out.exists():
        mani.touch(unit)
        return False
    manifest.write_if_changed(out, data)
    mani.record(unit, key, [out])
    return True
