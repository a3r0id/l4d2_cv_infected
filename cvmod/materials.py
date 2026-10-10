"""Phase 1: replace every infected material with a flat, unlit, x-ray colour.

The colour is baked into the texture rather than applied with `$color2`, so the
value that lands in the framebuffer is the authored RGB and mask extraction is
an exact-match test. Materials whose base texture carries real transparency
(hair cards) get a generated texture that keeps the original alpha and replaces
only the colour, so cutouts do not become solid quads.

Consumables (optional) keep their stock `$basetexture`, add `$ignorez`, and
brighten via `$color2` / `$selfillumtint`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import config, deadbodies, index as index_mod, manifest, vmt, vtf
from .features import Features

# Bump when the emitted VMT/VTF layout changes, to force a rebuild.
GENERATOR_VERSION = "5"

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


def _normalize_texture_ref(ref: str) -> str:
    """Stock VMTs sometimes put a .vtf suffix on $basetexture; strip it."""
    text = (ref or "").replace("\\", "/").strip().strip('"')
    if text.lower().endswith(".vtf"):
        text = text[:-4]
    return text


def _consumable_vmt_params(entry: index_mod.MaterialEntry) -> dict[str, str]:
    """Keep the stock albedo; draw through walls and brighten a little."""
    basetexture = _normalize_texture_ref(entry.basetexture)
    if not basetexture:
        raise ValueError("consumable material has no $basetexture")
    bright = config.CONSUMABLE_BRIGHTNESS
    tint = f"[{bright:g} {bright:g} {bright:g}]"
    params: dict[str, str] = {"$basetexture": basetexture}
    params.update(config.RENDER_FLAGS)
    params["$color2"] = tint
    params["$selfillumtint"] = tint
    if entry.alphatest:
        params["$alphatest"] = "1"
        params["$allowalphatocoverage"] = "0"
    if entry.additive:
        params["$additive"] = "1"
    if entry.translucent:
        params["$translucent"] = "1"
    return params


def explosive_ammo_texture_ref() -> str:
    return f"{config.FLAT_MATERIAL_DIR}/flat_explosive_ammo"


def _explosive_ammo_vmt_params() -> dict[str, str]:
    """Solid bright gold through walls — easy to spot in a pile of loot."""
    params: dict[str, str] = {"$basetexture": explosive_ammo_texture_ref()}
    params.update(config.RENDER_FLAGS)
    # Extra punch on top of the baked gold albedo.
    params["$selfillumtint"] = "[1.5 1.2 0.2]"
    params["$color2"] = "[1.2 1.0 0.35]"
    return params


def _is_consumable_entry(entry: index_mod.MaterialEntry, key_name: str) -> bool:
    return entry.cls == "consumable" or config.is_consumable_material(key_name)


def build(
    idx: index_mod.Index,
    mani: manifest.Manifest,
    force: bool = False,
    only: str | None = None,
    features: Features | None = None,
) -> Result:
    result = Result()
    features = features or Features()
    out_materials = config.BUILD / "materials"

    used_classes = sorted(
        cls
        for cls in ({e.cls for e in idx.materials.values()} | set(config.CLASS_COLORS))
        if cls != "consumable"
    )

    # Shared flat texture per infected class. Proxy materials (for hitbox meshes)
    # are optional and only written with --feat-hitbox-models.
    for cls in used_classes:
        color = config.CLASS_COLORS.get(cls, (255, 255, 255))
        texture = out_materials / f"{flat_texture_ref(cls)}.vtf"
        unit = f"materials/_flat/{cls}"

        data = vtf.build(color)
        key = manifest.sha(GENERATOR_VERSION, "flat-tex", repr(color), data)
        if not force and mani.is_current(unit, key) and texture.exists():
            mani.touch(unit)
            result.stats.skipped += 1
        else:
            manifest.write_if_changed(texture, data)
            mani.record(unit, key, [texture])
            result.stats.written += 1

        if features.hitbox_models:
            proxy_vmt = out_materials / f"{config.FLAT_MATERIAL_DIR}/proxy_{cls}.vmt"
            proxy_unit = f"materials/_proxy/{cls}"
            proxy_text = _render_vmt(
                {"$basetexture": flat_texture_ref(cls), **config.RENDER_FLAGS}
            )
            proxy_key = manifest.sha(GENERATOR_VERSION, "proxy-vmt", repr(color), proxy_text)
            if (
                not force
                and mani.is_current(proxy_unit, proxy_key)
                and proxy_vmt.exists()
            ):
                mani.touch(proxy_unit)
                result.stats.skipped += 1
            else:
                manifest.write_if_changed(proxy_vmt, proxy_text.encode("utf-8"))
                mani.record(proxy_unit, proxy_key, [proxy_vmt])
                result.stats.written += 1

    if features.consumables:
        gold = config.EXPLOSIVE_AMMO_COLOR
        gold_path = out_materials / f"{explosive_ammo_texture_ref()}.vtf"
        gold_unit = "materials/_flat/explosive_ammo"
        gold_data = vtf.build(gold)
        gold_key = manifest.sha(GENERATOR_VERSION, "explosive-ammo-gold", repr(gold), gold_data)
        if not force and mani.is_current(gold_unit, gold_key) and gold_path.exists():
            mani.touch(gold_unit)
            result.stats.skipped += 1
        else:
            manifest.write_if_changed(gold_path, gold_data)
            mani.record(gold_unit, gold_key, [gold_path])
            result.stats.written += 1

    for key_name, entry in sorted(idx.materials.items()):
        if only and only.lower() not in key_name.lower():
            continue
        if _is_consumable_entry(entry, key_name) and not features.consumables:
            continue
        # Corpse props reuse these paths; leave stock so piles stay uncoloured.
        if deadbodies.is_shared_infected_material(key_name):
            continue
        unit = f"materials/{key_name}"
        outputs: list[Path] = []

        if _is_consumable_entry(entry, key_name):
            if config.is_explosive_ammo_material(key_name):
                params = _explosive_ammo_vmt_params()
                vmt_text = _render_vmt(params)
                unit_key = manifest.sha(
                    GENERATOR_VERSION,
                    "consumable-explosive-gold",
                    vmt_text,
                    repr(config.EXPLOSIVE_AMMO_COLOR),
                )
                vmt_path = out_materials / f"{key_name}.vmt"
                if not force and mani.is_current(unit, unit_key):
                    mani.touch(unit)
                    result.stats.skipped += 1
                    continue
                manifest.write_if_changed(vmt_path, vmt_text.encode("utf-8"))
                mani.record(unit, unit_key, [vmt_path])
                result.stats.written += 1
                continue
            try:
                params = _consumable_vmt_params(entry)
            except ValueError as exc:
                result.errors.append((key_name, str(exc)))
                result.stats.failed += 1
                continue
            vmt_text = _render_vmt(params)
            unit_key = manifest.sha(
                GENERATOR_VERSION,
                "consumable-stock",
                vmt_text,
                repr(config.CONSUMABLE_BRIGHTNESS),
            )
            vmt_path = out_materials / f"{key_name}.vmt"
            if not force and mani.is_current(unit, unit_key):
                mani.touch(unit)
                result.stats.skipped += 1
                continue
            manifest.write_if_changed(vmt_path, vmt_text.encode("utf-8"))
            mani.record(unit, unit_key, [vmt_path])
            result.stats.written += 1
            continue

        color = config.CLASS_COLORS.get(entry.cls, (255, 255, 255))

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

    if features.trace:
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
        if features.trace:
            _write_client_tracers(mani, force, result)
        if features.map_retex:
            from . import mapretex

            wrote, unchanged, failed = mapretex.write(mani, force=force)
            result.stats.written += wrote
            result.stats.skipped += unchanged
            result.stats.failed += failed

    if not only:
        # Must run after every unit above has been touched or recorded.
        # Units for disabled features are left untouched, so prune removes them.
        removed = mani.prune("materials/")
        if not features.trace:
            removed.extend(mani.prune("scripts/"))
        if not features.hitbox_models:
            removed.extend(mani.prune("models/"))
            # Older builds recorded proxy VMTs on the flat unit; drop orphans.
            proxy_dir = out_materials / config.FLAT_MATERIAL_DIR
            if proxy_dir.exists():
                for path in sorted(proxy_dir.glob("proxy_*.vmt")):
                    if path.name == "proxy_consumable.vmt":
                        continue
                    path.unlink()
                    removed.append(path)
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
    """Solid white mask so self-illumination covers the whole infected."""
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
