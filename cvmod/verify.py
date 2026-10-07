"""Static checks on the build tree, run before trusting the addon in game."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import config, index as index_mod, vmt


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, ok, detail))

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def __str__(self) -> str:
        lines = []
        for c in self.checks:
            mark = "PASS" if c.ok else "FAIL"
            lines.append(f"  [{mark}] {c.name}")
            if c.detail:
                for line in c.detail.splitlines():
                    lines.append(f"         {line}")
        lines.append(f"  {'all checks passed' if self.ok else 'CHECKS FAILED'}")
        return "\n".join(lines)


def _build_materials() -> dict[str, Path]:
    root = config.BUILD / "materials"
    if not root.exists():
        return {}
    return {
        p.relative_to(root).with_suffix("").as_posix().lower(): p
        for p in root.rglob("*.vmt")
    }


def run(idx: index_mod.Index, check_textures: bool = True) -> Report:
    report = Report()
    built = _build_materials()
    materials_root = config.BUILD / "materials"

    # 1. Every indexed material is overridden.
    missing = sorted(k for k in idx.materials if k not in built)
    report.add(
        f"all {len(idx.materials)} indexed materials overridden",
        not missing,
        "" if not missing else f"missing {len(missing)}: " + ", ".join(missing[:10]),
    )

    # 2. Every source infected VMT is covered, including ones no model referenced.
    source_root = config.SRC_MATERIALS / "models" / "infected"
    source_keys = {
        p.relative_to(config.SRC_MATERIALS).with_suffix("").as_posix().lower()
        for p in source_root.rglob("*.vmt")
    }
    uncovered = sorted(source_keys - set(built))
    report.add(
        f"all {len(source_keys)} shipped infected VMTs covered",
        not uncovered,
        "" if not uncovered else f"uncovered {len(uncovered)}: " + ", ".join(uncovered[:10]),
    )

    # 3. Nothing outside the infected and generated-texture trees is touched.
    # The spitter puddle is a particle material, not an infected model.
    allowed = ("models/infected/", config.FLAT_MATERIAL_DIR + "/")
    puddle = set(config.SPITTER_PUDDLE_MATERIALS)
    tongue = set(config.SMOKER_TONGUE_MATERIALS)
    tracers = set(config.TRACER_MATERIALS)
    # Listen-server beam texture. It is not an infected material.
    shot_sprite = {"sprites/cv_tracer"}
    strays = sorted(
        k
        for k in built
        if not k.startswith(allowed)
        and k not in puddle
        and k not in tongue
        and k not in tracers
        and k not in shot_sprite
    )
    report.add(
        "no materials outside models/infected",
        not strays,
        "" if not strays else "strays: " + ", ".join(strays[:10]),
    )

    # 4. Every generated VMT parses and points at a texture that exists.
    bad_syntax: list[str] = []
    dangling: list[str] = []
    shaders: set[str] = set()
    puddle_bad: list[str] = []
    puddle_seen: set[str] = set()
    tongue_bad: list[str] = []
    tongue_seen: set[str] = set()
    smoker_texture = f"{config.FLAT_MATERIAL_DIR}/flat_smoker"
    tracer_texture = f"{config.FLAT_MATERIAL_DIR}/flat_tracer"
    tracer_bad: list[str] = []
    tracer_seen: set[str] = set()
    for key, path in sorted(built.items()):
        try:
            shader, body = vmt.parse_text(path.read_text(encoding="utf-8"))
        except Exception as exc:
            bad_syntax.append(f"{key}: {exc}")
            continue
        params = {k.lower(): v for k, v in body if isinstance(v, str)}
        if key in puddle:
            puddle_seen.add(key)
            ignorez = params.get("$ignorez", "").strip().strip('"')
            if ignorez in ("", "0"):
                puddle_bad.append(f"{key} missing $ignorez")
            continue
        if key in tongue:
            tongue_seen.add(key)
            ignorez = params.get("$ignorez", "").strip().strip('"')
            ref = params.get("$basetexture", "").strip().strip('"').replace("\\", "/")
            if ignorez in ("", "0") or ref.lower() != smoker_texture:
                tongue_bad.append(f"{key} -> {ref or '<none>'} ignorez={ignorez or '0'}")
            continue
        if key in shot_sprite:
            continue
        if key in tracers:
            tracer_seen.add(key)
            ref = params.get("$basetexture", "").strip().strip('"').replace("\\", "/")
            if ref.lower() != tracer_texture:
                tracer_bad.append(f"{key} -> {ref or '<none>'}")
            continue
        shaders.add(shader)
        ref = params.get("$basetexture", "")
        if not ref or not (materials_root / f"{ref}.vtf").exists():
            dangling.append(f"{key} -> {ref or '<none>'}")
        mask = params.get("$selfillummask", "").strip().strip('"').replace("\\", "/")
        if params.get("$selfillum", "").strip().strip('"') != "1" or not mask:
            dangling.append(f"{key} missing $selfillum")
        elif not (materials_root / f"{mask}.vtf").exists():
            dangling.append(f"{key} selfillum mask -> {mask}")
        if params.get("$disablevariation", "").strip().strip('"') != "1":
            dangling.append(f"{key} missing $disablevariation 1")
        if params.get("$allowdiffusemodulation", "").strip().strip('"') != "0":
            dangling.append(f"{key} missing $allowdiffusemodulation 0")
    report.add("every generated VMT parses", not bad_syntax, "\n".join(bad_syntax[:10]))
    report.add(
        "every $basetexture resolves inside the addon",
        not dangling,
        "\n".join(dangling[:10]),
    )
    report.add(
        "infected materials use the infected shader",
        shaders == {"VertexLitGeneric"},
        f"shaders found: {sorted(shaders)}",
    )
    missing_puddle = [k for k in config.SPITTER_PUDDLE_MATERIALS if k not in puddle_seen]
    report.add(
        "spitter puddle ignores depth",
        not puddle_bad and not missing_puddle,
        "\n".join(puddle_bad + [f"missing {k}" for k in missing_puddle]),
    )
    missing_tongue = [k for k in config.SMOKER_TONGUE_MATERIALS if k not in tongue_seen]
    report.add(
        "smoker tongue uses the smoker colour",
        not tongue_bad and not missing_tongue,
        "\n".join(tongue_bad + [f"missing {k}" for k in missing_tongue]),
    )
    missing_tracer = [k for k in config.TRACER_MATERIALS if k not in tracer_seen]
    report.add(
        "bullet tracers use the tracer colour",
        not tracer_bad and not missing_tracer,
        "\n".join(tracer_bad + [f"missing {k}" for k in missing_tracer]),
    )

    # 5. Valve's own reader accepts every generated texture.
    if check_textures:
        textures = sorted((materials_root / config.FLAT_MATERIAL_DIR).glob("*.vtf"))
        rejected: list[str] = []
        with tempfile.TemporaryDirectory(prefix="cvmod_vtf_") as tmp:
            for tex in textures:
                out = Path(tmp) / f"{tex.stem}.tga"
                subprocess.run(
                    [str(config.GAME_ROOT / "bin" / "vtf2tga.exe"), "-i", str(tex), "-o", str(out)],
                    capture_output=True,
                    text=True,
                )
                if not out.exists():
                    rejected.append(tex.name)
        report.add(
            f"all {len(textures)} generated VTFs accepted by vtf2tga",
            not rejected,
            "rejected: " + ", ".join(rejected) if rejected else "",
        )

    # 6. Capture config and the shot-line overlay ship with the addon.
    cfg = config.BUILD / "cfg" / "cv_capture.cfg"
    report.add("cv_capture.cfg present", cfg.exists(), str(cfg) if not cfg.exists() else "")
    shotlines = config.BUILD / "scripts" / "vscripts" / "mapspawn_addon.nut"
    shotline_text = shotlines.read_text(encoding="utf-8") if shotlines.exists() else ""
    tracer_vmt = config.BUILD / "materials" / "sprites" / "cv_tracer.vmt"
    report.add(
        "shot-line script present",
        "OnGameEvent_bullet_impact" in shotline_text
        and "env_beam" in shotline_text
        and "mat_hdr_level" in shotline_text
        and tracer_vmt.exists(),
        str(shotlines) if not shotlines.exists() else "",
    )

    _check_models(report, idx, built)
    return report


def _check_models(report: Report, idx: index_mod.Index, built_materials: dict[str, Path]) -> None:
    """Phase 2 checks: the compiled proxy models must be loadable and complete."""
    from . import mdl

    root = config.BUILD / "models"
    models = sorted(root.rglob("*.mdl")) if root.exists() else []
    if not models:
        report.add("proxy models present", False, "no compiled models in build/models")
        return

    incomplete: list[str] = []
    unreadable: list[str] = []
    lost_anims: list[str] = []
    missing_mats: list[str] = []
    bone_drift: list[str] = []
    phy_mismatch: list[str] = []

    for path in models:
        rel = path.relative_to(root).as_posix()
        base = str(path)[: -len(".mdl")]
        # The engine needs all three files; a lone .mdl crashes the loader.
        for ext in (".vvd", ".dx90.vtx"):
            if not Path(base + ext).exists():
                incomplete.append(f"{rel} missing {ext}")
        try:
            built = mdl.read(path)
        except mdl.MdlError as exc:
            unreadable.append(f"{rel}: {exc}")
            continue

        source = config.SRC_MODELS / rel
        if source.exists():
            try:
                original = mdl.read(source)
            except mdl.MdlError:
                original = None
            if original is not None:
                names_in = [b.name for b in original.bones]
                names_out = [b.name for b in built.bones]
                if names_in != names_out:
                    bone_drift.append(f"{rel}: {len(names_in)} -> {len(names_out)} bones")

        # Animations live in the shared anim_*.mdl; that link must survive and
        # must point at a model the game actually ships.
        if not built.include_models:
            lost_anims.append(rel)
        for inc in built.include_models:
            key = inc.replace("\\", "/").lower()
            if not (config.SRC_MODELS / key[len("models/"):]).exists():
                lost_anims.append(f"{rel} -> {inc} (not found)")

        for tex in built.textures:
            found = any(
                f"{d}{tex}".replace("\\", "/").lower().lstrip("/") in built_materials
                for d in built.cdmaterials or [""]
            )
            if not found:
                missing_mats.append(f"{rel} -> {tex}")

        phy = Path(base + ".phy")
        if phy.exists():
            stored = int.from_bytes(phy.read_bytes()[12:16], "little", signed=True)
            if stored != built.checksum:
                phy_mismatch.append(f"{rel}: phy {stored} != mdl {built.checksum}")

    report.add(f"all {len(models)} proxy models readable", not unreadable, "\n".join(unreadable[:10]))
    report.add("every proxy ships .vvd and .vtx", not incomplete, "\n".join(incomplete[:10]))
    report.add("every proxy keeps its skeleton", not bone_drift, "\n".join(bone_drift[:10]))
    report.add("every proxy keeps $includemodel animations", not lost_anims, "\n".join(lost_anims[:10]))
    report.add("every proxy material exists in the addon", not missing_mats, "\n".join(missing_mats[:10]))
    report.add("every .phy checksum matches its .mdl", not phy_mismatch, "\n".join(phy_mismatch[:10]))


def color_table(idx: index_mod.Index) -> str:
    counts: dict[str, int] = {}
    for entry in idx.materials.values():
        counts[entry.cls] = counts.get(entry.cls, 0) + 1
    lines = [f"  {'class':<9} {'rgb':<17} {'hex':<9} materials  models"]
    model_counts: dict[str, int] = {}
    for m in idx.models.values():
        model_counts[m.cls] = model_counts.get(m.cls, 0) + 1
    for cls in sorted(counts, key=lambda c: config.CLASS_PRECEDENCE.get(c, 99)):
        r, g, b = config.CLASS_COLORS.get(cls, (255, 255, 255))
        lines.append(
            f"  {cls:<9} {str((r, g, b)):<17} #{r:02X}{g:02X}{b:02X}   "
            f"{counts[cls]:>6}     {model_counts.get(cls, 0):>5}"
        )
    return "\n".join(lines)
