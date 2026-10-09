"""Optional addon features selected at pack/deploy time.

Core (default) ships only the infected material and proxy overrides.
`--feat-override-consumables` x-rays stock pickup textures (slightly brightened).
`--feat-trace` adds cheat-only shot scripts, capture cfg, and client tracer hooks.
`--feat-cleanup` adds an autoexec patch that caps ragdolls/decals and binds C to clear clutter.
`--feat-sounds` converts and installs custom sounds from config.json.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass(frozen=True)
class Features:
    consumables: bool = False
    trace: bool = False
    cleanup: bool = False
    sounds: bool = False

    def label(self) -> str:
        parts = ["infected"]
        if self.consumables:
            parts.append("consumables")
        if self.trace:
            parts.append("trace")
        if self.cleanup:
            parts.append("cleanup")
        if self.sounds:
            parts.append("sounds")
        return "+".join(parts)


# Paths under build/ that only ship with --feat-trace.
TRACE_PREFIXES: tuple[str, ...] = (
    "scripts/",
    "cfg/",
)

TRACE_MATERIAL_KEYS: frozenset[str] = frozenset(
    (*config.TRACER_MATERIALS, "sprites/cv_tracer")
)

TRACE_FLAT_STEMS: frozenset[str] = frozenset({"flat_tracer"})


def from_args(args) -> Features:
    return Features(
        consumables=bool(getattr(args, "feat_override_consumables", False)),
        trace=bool(getattr(args, "feat_trace", False)),
        cleanup=bool(getattr(args, "feat_cleanup", False)),
        sounds=bool(getattr(args, "feat_sounds", False)),
    )


def _norm(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("/").lower()


def _material_key(rel: str) -> str | None:
    rel = _norm(rel)
    if not rel.startswith("materials/"):
        return None
    key = rel[len("materials/") :]
    if key.endswith(".vmt") or key.endswith(".vtf"):
        return key.rsplit(".", 1)[0]
    return key


def is_consumable_build_path(rel: str) -> bool:
    rel = _norm(rel)
    key = _material_key(rel)
    if key is not None:
        if key == f"{config.FLAT_MATERIAL_DIR}/flat_consumable":
            return True
        if key == f"{config.FLAT_MATERIAL_DIR}/flat_explosive_ammo":
            return True
        if key == f"{config.FLAT_MATERIAL_DIR}/proxy_consumable":
            return True
        return config.is_consumable_material(key)
    if rel.startswith("models/w_models/weapons/w_eq_"):
        return True
    return False


def is_trace_build_path(rel: str) -> bool:
    rel = _norm(rel)
    if any(rel == p or rel.startswith(p) for p in TRACE_PREFIXES):
        return True
    key = _material_key(rel)
    if key is None:
        return False
    if key in TRACE_MATERIAL_KEYS:
        return True
    stem = Path(key).name
    return stem in TRACE_FLAT_STEMS


_MODEL_SUFFIXES = (".mdl", ".vvd", ".vtx", ".phy", ".ani")


def is_packed_model(rel: str) -> bool:
    """Studio files under models/. Servers consistency-check these and disconnect."""
    rel = _norm(rel)
    return rel.startswith("models/") and rel.endswith(_MODEL_SUFFIXES)


def include_build_path(rel: str, features: Features) -> bool:
    """Whether a path under build/ belongs in the staged addon."""
    # Replacing models/infected/*.mdl fails sv_consistency ("enforcing consistency
    # for this file"). Flat materials recolor the stock mesh without that check.
    if is_packed_model(rel):
        return False
    if is_consumable_build_path(rel) and not features.consumables:
        return False
    if is_trace_build_path(rel) and not features.trace:
        return False
    return True


def filter_index_materials(idx, features: Features):
    """Drop indexed materials that the selected features will not ship."""
    keep = {}
    for key, entry in idx.materials.items():
        if entry.cls == "consumable" and not features.consumables:
            continue
        if config.is_consumable_material(key) and not features.consumables:
            continue
        keep[key] = entry
    idx.materials = keep
    if not features.consumables:
        idx.models = {k: v for k, v in idx.models.items() if v.cls != "consumable"}
    return idx
