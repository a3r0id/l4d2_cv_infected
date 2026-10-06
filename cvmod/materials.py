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


def _render_vmt(params: dict[str, str]) -> str:
    width = max(len(k) for k in params)
    lines = ["UnlitGeneric", "{"]
    for key, value in params.items():
        lines.append(f'\t{key.ljust(width)} "{value}"')
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


CAPTURE_CFG = """\
// cv_capture.cfg - run with: exec cv_capture
//
// The infected materials are unlit, but Source still gamma-corrects and
// tonemaps the frame. These settings flatten post-processing so sampled pixels
// stay close to the authored RGB values.

mat_hdr_level 0
mat_bloomscale 0
mat_disable_bloom 1
mat_colorcorrection 0
mat_motion_blur_enabled 0
mat_grain_scale_override 0
mat_antialias 0
mat_software_aa_strength 0
mat_specular 0
r_dynamic 0
muzzleflash_light 0

// No fog tinting the flat colours.
fog_override 1
fog_enable 0

// Keep the frame clear of anything that is not an infected.
r_drawviewmodel 0
cl_drawhud 0
net_graph 0

// Local servers only: allow the addon's modified content.
sv_consistency 0
sv_pure 0

// Shot paths are drawn by scripts/vscripts/mapspawn_addon.nut (listen host,
// pink, a few seconds). They are separate from this cfg.
//   script CVShotLinesEnabled <- false

echo "[cv_infected] capture settings applied"
"""


def write_capture_cfg(mani: manifest.Manifest, force: bool = False) -> bool:
    out = config.BUILD / "cfg" / "cv_capture.cfg"
    data = CAPTURE_CFG.encode("utf-8")
    key = manifest.sha(GENERATOR_VERSION, data)
    unit = "materials/_cfg/cv_capture"
    if not force and mani.is_current(unit, key) and out.exists():
        mani.touch(unit)
        return False
    manifest.write_if_changed(out, data)
    mani.record(unit, key, [out])
    return True
