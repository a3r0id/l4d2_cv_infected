"""Phase 2: replace infected geometry with boxes built from their own hitboxes.

Each hitbox is an axis-aligned box in a bone's local space, which is exactly
the volume the engine tests bullets against. Rendering that volume instead of
the art mesh gives a minimal, unambiguous silhouette that also shows precisely
where a shot connects.
"""

from __future__ import annotations

import shutil
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import compile as compile_mod
from . import config, index as index_mod, manifest, mdl, qc, smd
from .features import Features

GENERATOR_VERSION = "3"

# Corner ordering: bit 0 = +x, bit 1 = +y, bit 2 = +z.
_FACES = (
    ((0, 4, 6, 2), (-1.0, 0.0, 0.0)),
    ((1, 3, 7, 5), (1.0, 0.0, 0.0)),
    ((0, 1, 5, 4), (0.0, -1.0, 0.0)),
    ((2, 6, 7, 3), (0.0, 1.0, 0.0)),
    ((0, 2, 3, 1), (0.0, 0.0, -1.0)),
    ((4, 5, 7, 6), (0.0, 0.0, 1.0)),
)
_FACE_UV = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


# A compiled proxy is only accepted if its skeleton and geometry land where
# the source model says they should.
MAX_SKELETON_ERROR = 1e-2
MAX_VERTEX_ERROR = 1e-1


@dataclass
class ModelResult:
    stem: str
    ok: bool
    reason: str = ""
    # Some models are deliberately left alone rather than having failed to
    # build; they still get the phase 1 flat materials.
    skipped: bool = False
    boxes: int = 0
    bones_in: int = 0
    bones_out: int = 0
    skeleton_error: float = 0.0
    vertex_error: float = 0.0
    outputs: list[Path] = field(default_factory=list)


@dataclass
class Result:
    stats: manifest.Stats = field(default_factory=manifest.Stats)
    models: list[ModelResult] = field(default_factory=list)

    def summary(self) -> str:
        built = [m for m in self.models if m.ok]
        skipped = [m for m in self.models if not m.ok and m.skipped]
        failed = [m for m in self.models if not m.ok and not m.skipped]
        lines = [f"models: {self.stats}"]
        if built:
            boxes = sum(m.boxes for m in built)
            lines.append(f"  {len(built)} proxy models, {boxes} hitbox volumes total")
            lines.append(
                f"  worst skeleton error {max(m.skeleton_error for m in built):.2e}, "
                f"worst vertex error {max(m.vertex_error for m in built):.2e}"
            )
            collapsed = [m for m in built if m.bones_out and m.bones_out != m.bones_in]
            if collapsed:
                lines.append(f"  bone count changed on {len(collapsed)}:")
                for m in collapsed[:10]:
                    lines.append(f"      {m.stem}: {m.bones_in} -> {m.bones_out}")
        for label, group in (("left as-is", skipped), ("FAILED, fell back to original mesh", failed)):
            if not group:
                continue
            lines.append(f"  {len(group)} {label}:")
            tally: dict[str, int] = {}
            for m in group:
                tally[m.reason] = tally.get(m.reason, 0) + 1
            for reason, count in sorted(tally.items(), key=lambda kv: -kv[1]):
                lines.append(f"      {count:>3}  {reason}")
        return "\n".join(lines)


def box_triangles(
    matrix: np.ndarray,
    bone: int,
    bbmin: tuple[float, float, float],
    bbmax: tuple[float, float, float],
    material: str,
    inflate: float = 0.0,
) -> list[smd.Triangle]:
    """One hitbox volume, as 12 triangles weighted entirely to its bone."""
    lo = np.array(bbmin, dtype=np.float64) - inflate
    hi = np.array(bbmax, dtype=np.float64) + inflate
    corners = []
    for i in range(8):
        local = np.array(
            [hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2], 1.0]
        )
        corners.append((matrix @ local)[:3])

    rotation = matrix[:3, :3]
    triangles: list[smd.Triangle] = []
    for quad, local_normal in _FACES:
        normal = rotation @ np.array(local_normal)
        norm = float(np.linalg.norm(normal))
        normal = normal / norm if norm > 1e-9 else np.array([0.0, 0.0, 1.0])
        verts = [
            smd.Vertex(bone=bone, pos=tuple(corners[q]), normal=tuple(normal), uv=_FACE_UV[k])
            for k, q in enumerate(quad)
        ]
        triangles.append(smd.Triangle(material, (verts[0], verts[1], verts[2])))
        triangles.append(smd.Triangle(material, (verts[0], verts[2], verts[3])))
    return triangles


def build_mesh(model: mdl.Mdl, material: str, inflate: float = 0.0) -> list[smd.Triangle]:
    if not model.hitbox_sets:
        return []
    matrices = smd.model_matrices(model.bones)
    triangles: list[smd.Triangle] = []
    for box in model.hitbox_sets[0].boxes:
        if not (0 <= box.bone < len(matrices)):
            continue
        triangles.extend(
            box_triangles(matrices[box.bone], box.bone, box.bbmin, box.bbmax, material, inflate)
        )
    return triangles


def proxy_material(cls: str) -> str:
    return f"proxy_{cls}"


def _bone_to_model(model: mdl.Mdl) -> list[np.ndarray]:
    """Rest-pose transforms taken from poseToBone, independent of any Euler convention."""
    out = []
    for bone in model.bones:
        m = np.eye(4)
        m[:3, :4] = np.array(bone.pose_to_bone).reshape(3, 4)
        out.append(np.linalg.inv(m))
    return out


def skeleton_error(original: mdl.Mdl, built: mdl.Mdl) -> float:
    if len(original.bones) != len(built.bones):
        return float("inf")
    if [b.name for b in original.bones] != [b.name for b in built.bones]:
        return float("inf")
    a, b = _bone_to_model(original), _bone_to_model(built)
    return max(float(np.abs(a[i][:3, :4] - b[i][:3, :4]).max()) for i in range(len(a)))


def vertex_error(original: mdl.Mdl, vvd_path: Path, expected: np.ndarray) -> float:
    """Largest gap between a compiled vertex and the nearest hitbox corner."""
    buf = vvd_path.read_bytes()
    if len(buf) < 64:
        return float("inf")
    count = struct.unpack_from("<8i", buf, 16)[0]
    start = struct.unpack_from("<i", buf, 56)[0]
    if count <= 0 or start + count * 48 > len(buf):
        return float("inf")
    got = np.array([struct.unpack_from("<3f", buf, start + i * 48 + 16) for i in range(count)])
    deltas = np.linalg.norm(got[:, None, :] - expected[None, :, :], axis=2)
    return float(deltas.min(axis=1).max())


def expected_corners(model: mdl.Mdl, inflate: float = 0.0) -> np.ndarray:
    matrices = smd.model_matrices(model.bones)
    points: list[np.ndarray] = []
    for box in model.hitbox_sets[0].boxes:
        if not (0 <= box.bone < len(matrices)):
            continue
        lo = np.array(box.bbmin) - inflate
        hi = np.array(box.bbmax) + inflate
        for i in range(8):
            corner = np.array(
                [hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2], 1.0]
            )
            points.append((matrices[box.bone] @ corner)[:3])
    return np.array(points)


def build_one(
    model_path: Path,
    cls: str,
    work_root: Path,
    inflate: float = 0.0,
    define_bones: bool = False,
) -> tuple[ModelResult, str]:
    """Generate, compile and collect a single proxy model. Returns (result, log)."""
    stem = model_path.stem
    try:
        model = mdl.read(model_path)
    except mdl.MdlError as exc:
        return ModelResult(stem, False, f"unreadable MDL ({exc})"), ""

    if not model.hitbox_sets or not model.hitbox_sets[0].boxes:
        return ModelResult(stem, False, "no hitboxes to build from", skipped=True), ""
    # Consumables are static world pickups: they have no shared anim model, and
    # the QC already writes a local idle sequence. Infected gibs still need their
    # own sequences, so leave those alone.
    static_ok = cls == "consumable"
    if not model.include_models and not static_ok:
        return ModelResult(stem, False, "self-contained animations", skipped=True), ""

    material = proxy_material(cls)
    triangles = build_mesh(model, material, inflate)
    if not triangles:
        return ModelResult(stem, False, "no usable hitboxes"), ""

    work = work_root / stem
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    smd_name = f"{stem}_proxy.smd"
    smd.write(work / smd_name, model.bones, triangles)
    qc_path = work / f"{stem}.qc"
    qc_path.write_text(
        qc.build(model, smd_name, config.FLAT_MATERIAL_DIR + "/", define_bones=define_bones),
        encoding="utf-8",
    )

    compiled = compile_mod.run(qc_path)
    gamedir = compile_mod.scratch_gamedir()
    outputs = compile_mod.collect(gamedir, model.internal_name, config.BUILD)
    built_mdl = next((p for p in outputs if p.suffix.lower() == ".mdl"), None)
    if built_mdl is None:
        return ModelResult(stem, False, "studiomdl produced no .mdl"), compiled.log

    def reject(reason: str) -> tuple[ModelResult, str]:
        for path in outputs:
            path.unlink(missing_ok=True)
        manifest.remove_empty_dirs(config.BUILD)
        return ModelResult(stem, False, reason, bones_in=len(model.bones)), compiled.log

    try:
        rebuilt = mdl.read(built_mdl)
    except mdl.MdlError as exc:
        return reject(f"compiled MDL unreadable ({exc})")

    skel_err = skeleton_error(model, rebuilt)
    if skel_err > MAX_SKELETON_ERROR:
        return reject(f"skeleton drifted by {skel_err:.4f}")

    vvd = next((p for p in outputs if p.suffix.lower() == ".vvd"), None)
    if vvd is None:
        return reject("studiomdl produced no .vvd")
    vert_err = vertex_error(model, vvd, expected_corners(model, inflate))
    if vert_err > MAX_VERTEX_ERROR:
        return reject(f"vertices off by {vert_err:.4f}")

    if model.include_models and not rebuilt.include_models:
        return reject("$includemodel lost, animations would break")

    phy = compile_mod.copy_phy(model_path, built_mdl)
    if phy is not None:
        outputs.append(phy)

    return (
        ModelResult(
            stem=stem,
            ok=True,
            boxes=len(model.hitbox_sets[0].boxes),
            bones_in=len(model.bones),
            bones_out=len(rebuilt.bones),
            skeleton_error=skel_err,
            vertex_error=vert_err,
            outputs=outputs,
        ),
        compiled.log,
    )


def build(
    idx: index_mod.Index,
    mani: manifest.Manifest,
    force: bool = False,
    only: str | None = None,
    keep_work: bool = False,
    inflate: float = 0.0,
    define_bones: bool = True,
    features: Features | None = None,
) -> Result:
    result = Result()
    features = features or Features()
    work_root = config.WORK / "qc"
    work_root.mkdir(parents=True, exist_ok=True)
    logs_root = config.WORK / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)

    # Consumables keep their stock meshes; only their materials are overridden.
    targets = [
        entry
        for entry in sorted(idx.models.values(), key=lambda e: e.stem)
        if (not only or only.lower() in entry.stem.lower())
        and entry.cls != "consumable"
    ]

    for entry in targets:
        source = config.SRC_MODELS / entry.rel_path
        if not source.exists():
            continue
        unit = f"models/{entry.stem}"
        key = manifest.sha(
            GENERATOR_VERSION,
            entry.cls,
            str(inflate),
            str(define_bones),
            manifest.file_sha(source),
        )
        if not force and mani.is_current(unit, key):
            mani.touch(unit)
            result.stats.skipped += 1
            continue

        model_result, log = build_one(
            source, entry.cls, work_root, inflate=inflate, define_bones=define_bones
        )
        result.models.append(model_result)
        if log:
            (logs_root / f"{entry.stem}.log").write_text(log, encoding="utf-8")

        if model_result.ok:
            mani.record(unit, key, model_result.outputs)
            result.stats.written += 1
        elif not model_result.skipped:
            # Leaving no model files behind means the stock mesh is used, with
            # the phase 1 flat materials still applied.
            result.stats.failed += 1

        if not keep_work:
            shutil.rmtree(work_root / entry.stem, ignore_errors=True)

    if not only:
        removed = mani.prune("models/")
        result.stats.removed = len(removed)

    return result
