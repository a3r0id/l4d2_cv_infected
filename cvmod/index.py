"""Builds the authoritative map of infected model -> class -> materials.

Mapping materials by folder name alone is unsafe: `hulk.mdl` lists
`models\\infected\\common\\` in its cdmaterials and `smoker/boomer_hair.vmt` is
named after the wrong class. So the mapping is derived from the model side by
resolving each MDL's cdmaterials against its texture names, exactly the way the
engine does. Anything left over is swept up by folder as a fallback and
reported, so nothing is silently missed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config, mdl, vmt, vpkutil

# Fallback only, for VMTs no model referenced.
DIR_CLASS = {
    "boomer": "boomer",
    "charger": "charger",
    "common": "common",
    "gibs": "gibs",
    "hulk": "tank",
    "hunter": "hunter",
    "jockey": "jockey",
    "smoker": "smoker",
    "spitter": "spitter",
    "witch": "witch",
}


@dataclass
class MaterialEntry:
    key: str  # path under materials/, posix, lowercase, no extension
    cls: str
    source: str  # "model" or "directory"
    models: list[str] = field(default_factory=list)
    claimed_by: list[str] = field(default_factory=list)  # all classes that referenced it
    shader: str = ""
    basetexture: str = ""
    alphatest: bool = False
    additive: bool = False
    translucent: bool = False
    error: str = ""


@dataclass
class ModelEntry:
    stem: str
    rel_path: str  # under models/, posix
    cls: str
    materials: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    bones: int = 0
    hitboxes: int = 0
    include_models: list[str] = field(default_factory=list)


@dataclass
class Index:
    materials: dict[str, MaterialEntry] = field(default_factory=dict)
    models: dict[str, ModelEntry] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "materials": {k: asdict(v) for k, v in sorted(self.materials.items())},
                "models": {k: asdict(v) for k, v in sorted(self.models.items())},
            },
            indent=1,
        )

    @staticmethod
    def from_json(text: str) -> "Index":
        raw = json.loads(text)
        idx = Index()
        for k, v in raw.get("materials", {}).items():
            idx.materials[k] = MaterialEntry(**v)
        for k, v in raw.get("models", {}).items():
            idx.models[k] = ModelEntry(**v)
        return idx

    def by_class(self) -> dict[str, list[MaterialEntry]]:
        out: dict[str, list[MaterialEntry]] = {}
        for entry in self.materials.values():
            out.setdefault(entry.cls, []).append(entry)
        return out


def _norm(value: str) -> str:
    return value.replace("\\", "/").strip().strip("/").lower()


def material_path(key: str) -> Path:
    return config.SRC_MATERIALS / f"{key}.vmt"


def _candidates(cdmaterials: list[str], texture: str) -> list[str]:
    """Replicate the engine's lookup: each cdmaterials prefix, then the bare name."""
    tex = _norm(texture)
    seen: list[str] = []
    for cd in cdmaterials:
        candidate = f"{_norm(cd)}/{tex}" if cd else tex
        if candidate not in seen:
            seen.append(candidate)
    if tex not in seen:
        seen.append(tex)
    return seen


def _claim(index: Index, key: str, cls: str, source: str, model: str | None) -> None:
    entry = index.materials.get(key)
    if entry is None:
        entry = MaterialEntry(key=key, cls=cls, source=source)
        index.materials[key] = entry
    if cls not in entry.claimed_by:
        entry.claimed_by.append(cls)
    if model and model not in entry.models:
        entry.models.append(model)
    # Lower precedence value wins; a model claim always beats a directory guess.
    incumbent = (entry.source != "model", config.CLASS_PRECEDENCE.get(entry.cls, 99))
    challenger = (source != "model", config.CLASS_PRECEDENCE.get(cls, 99))
    if challenger < incumbent:
        entry.cls = cls
        entry.source = source


def _describe(entry: MaterialEntry) -> None:
    path = material_path(entry.key)
    if not path.exists():
        entry.error = "missing"
        return
    try:
        material = vmt.resolve(path)
    except vmt.VmtError as exc:
        entry.error = str(exc)
        return
    entry.shader = material.shader
    entry.basetexture = material.get("$basetexture", "") or ""
    entry.alphatest = material.truthy("$alphatest")
    entry.additive = material.truthy("$additive")
    entry.translucent = material.truthy("$translucent")


def _index_model(index: Index, path: Path, cls: str) -> None:
    if not mdl.has_geometry(path):
        return  # animation-only model, nothing to recolour
    try:
        model = mdl.read(path)
    except mdl.MdlError:
        return

    rel = path.relative_to(config.SRC_MODELS).as_posix()
    entry = ModelEntry(
        stem=path.stem,
        rel_path=rel,
        cls=cls,
        bones=len(model.bones),
        hitboxes=len(model.hitbox_sets[0].boxes) if model.hitbox_sets else 0,
        include_models=list(model.include_models),
    )

    for texture in model.textures:
        hit = next(
            (c for c in _candidates(model.cdmaterials, texture) if material_path(c).exists()),
            None,
        )
        if hit is None:
            if texture.strip():
                entry.unresolved.append(texture)
            continue
        if config.is_excluded_material(hit):
            continue
        if hit not in entry.materials:
            entry.materials.append(hit)
        _claim(index, hit, cls, "model", path.stem)

    index.models[path.stem] = entry


def ensure_consumable_models() -> list[Path]:
    """Pull world pickup models out of the game VPK when the checkout lacks them."""
    required: list[str] = []
    optional: list[str] = []
    for stem in config.CONSUMABLE_MODEL_STEMS:
        base = f"models/w_models/weapons/{stem}"
        required.extend([base + ".mdl", base + ".vvd", base + ".dx90.vtx"])
        optional.append(base + ".phy")
    try:
        written = vpkutil.extract_game_files(required, config.SRC)
        written.extend(vpkutil.extract_game_files(optional, config.SRC, optional=True))
        return written
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        print(f"warning: could not extract consumable models: {exc}")
        return []


def build() -> Index:
    index = Index()
    ensure_consumable_models()

    for path in sorted(config.SRC_INFECTED_MODELS.rglob("*.mdl")):
        rel_path = path.relative_to(config.SRC_INFECTED_MODELS)
        cls = config.classify_model(path.stem, rel_path.parts[:-1])
        _index_model(index, path, cls)

    for stem in config.CONSUMABLE_MODEL_STEMS:
        path = config.SRC_MODELS / "w_models" / "weapons" / f"{stem}.mdl"
        if path.exists():
            _index_model(index, path, "consumable")

    # Defensive sweep: any infected VMT no model referenced still gets recoloured.
    infected_root = config.SRC_MATERIALS / "models" / "infected"
    for path in sorted(infected_root.rglob("*.vmt")):
        key = path.relative_to(config.SRC_MATERIALS).with_suffix("").as_posix().lower()
        if key in index.materials:
            continue
        rel_parts = path.relative_to(infected_root).parts
        cls = DIR_CLASS.get(rel_parts[0].lower(), "common") if len(rel_parts) > 1 else "common"
        _claim(index, key, cls, "directory", None)

    # Same for consumable materials the world models did not name directly
    # (viewmodels, alternate ammo labels).
    for path in sorted(config.SRC_MATERIALS.rglob("*.vmt")):
        key = path.relative_to(config.SRC_MATERIALS).with_suffix("").as_posix().lower()
        if key in index.materials or not config.is_consumable_material(key):
            continue
        _claim(index, key, "consumable", "directory", None)

    for entry in index.materials.values():
        _describe(entry)

    return index


def report(index: Index) -> str:
    lines: list[str] = []
    by_class = index.by_class()

    lines.append("MODELS")
    per_class: dict[str, list[ModelEntry]] = {}
    for m in index.models.values():
        per_class.setdefault(m.cls, []).append(m)
    for cls in sorted(per_class, key=lambda c: config.CLASS_PRECEDENCE.get(c, 99)):
        entries = per_class[cls]
        lines.append(f"  {cls:<9} {len(entries):>3} models")
    lines.append(f"  {'TOTAL':<9} {len(index.models):>3} models")

    lines.append("")
    lines.append("MATERIALS")
    for cls in sorted(by_class, key=lambda c: config.CLASS_PRECEDENCE.get(c, 99)):
        entries = by_class[cls]
        from_dir = sum(1 for e in entries if e.source == "directory")
        color = config.CLASS_COLORS.get(cls, (255, 255, 255))
        lines.append(
            f"  {cls:<9} {len(entries):>3} materials "
            f"({from_dir} folder-derived)  rgb{color}"
        )
    lines.append(f"  {'TOTAL':<9} {len(index.materials):>3} materials")

    contested = [e for e in index.materials.values() if len(e.claimed_by) > 1]
    if contested:
        lines.append("")
        lines.append(f"CONTESTED ({len(contested)}) - claimed by several classes, resolved by precedence")
        for e in sorted(contested, key=lambda e: e.key):
            lines.append(f"  {e.key}")
            lines.append(f"      claimed by {sorted(e.claimed_by)} -> {e.cls}")

    special = [e for e in index.materials.values() if e.alphatest or e.additive or e.translucent]
    if special:
        lines.append("")
        lines.append(
            f"SPECIAL BLENDING ({len(special)}) - candidates for an alpha-preserving texture; "
            "those that turn out to be fully opaque are flattened like everything else"
        )
        for e in sorted(special, key=lambda e: e.key):
            kinds = [
                k
                for k, v in (("alphatest", e.alphatest), ("additive", e.additive), ("translucent", e.translucent))
                if v
            ]
            lines.append(f"  {e.key:<55} {'+'.join(kinds)}")

    errored = [e for e in index.materials.values() if e.error]
    if errored:
        lines.append("")
        lines.append(f"UNREADABLE ({len(errored)})")
        for e in sorted(errored, key=lambda e: e.key):
            lines.append(f"  {e.key}: {e.error}")

    unresolved = [(m.stem, t) for m in index.models.values() for t in m.unresolved]
    if unresolved:
        lines.append("")
        lines.append(f"UNRESOLVED TEXTURE REFS ({len(unresolved)}) - no VMT found on disk")
        for stem, tex in sorted(unresolved):
            lines.append(f"  {stem:<40} {tex}")

    lines.append("")
    return "\n".join(lines)


def save(index: Index) -> None:
    config.WORK.mkdir(parents=True, exist_ok=True)
    config.INDEX_JSON.write_text(index.to_json(), encoding="utf-8")
    config.INDEX_REPORT.write_text(report(index), encoding="utf-8")


def load() -> Index:
    if not config.INDEX_JSON.exists():
        return build()
    return Index.from_json(config.INDEX_JSON.read_text(encoding="utf-8"))
