"""Reader for Source MDL v49 (the format L4D2 ships).

Only the parts the pipeline needs: bones, hitboxes, attachments, material
references and the header metadata a QC has to reproduce.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

HDR = "<4sii64si"

BONE_STRIDE = 216
# mstudiobone_t field offsets. Laid out as: sznameindex, parent,
# bonecontroller[6], pos, quat, rot, posscale, rotscale, poseToBone,
# qAlignment, flags, proctype, procindex, physicsbone, surfacepropidx,
# contents, unused[8] -- which sums to exactly BONE_STRIDE.
BONE_POS = 32
BONE_QUAT = 44
BONE_ROT = 60
BONE_POSE_TO_BONE = 96
BONE_FLAGS = 160
BONE_SURFACEPROP = 176
BONE_CONTENTS = 180
BBOX_STRIDE = 68
HBOXSET_STRIDE = 12
ATTACHMENT_STRIDE = 92
TEXTURE_STRIDE = 64
BODYPART_STRIDE = 16
MODELGROUP_STRIDE = 8


class MdlError(Exception):
    pass


@dataclass
class Bone:
    index: int
    name: str
    parent: int
    pos: tuple[float, float, float]
    quat: tuple[float, float, float, float]
    rot: tuple[float, float, float]
    pose_to_bone: tuple[float, ...]  # 12 floats, row-major 3x4, model -> bone
    surfaceprop: str
    contents: int
    flags: int


@dataclass
class HitBox:
    bone: int
    group: int
    bbmin: tuple[float, float, float]
    bbmax: tuple[float, float, float]
    name: str


@dataclass
class HitBoxSet:
    name: str
    boxes: list[HitBox]


@dataclass
class Attachment:
    name: str
    flags: int
    bone: int
    matrix: tuple[float, ...]  # 12 floats, row-major 3x4


@dataclass
class Mdl:
    path: Path
    version: int
    checksum: int
    internal_name: str
    flags: int
    eye_position: tuple[float, float, float]
    illum_position: tuple[float, float, float]
    hull_min: tuple[float, float, float]
    hull_max: tuple[float, float, float]
    view_bbmin: tuple[float, float, float]
    view_bbmax: tuple[float, float, float]
    mass: float
    contents: int
    surfaceprop: str
    bones: list[Bone] = field(default_factory=list)
    hitbox_sets: list[HitBoxSet] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    textures: list[str] = field(default_factory=list)
    cdmaterials: list[str] = field(default_factory=list)
    include_models: list[str] = field(default_factory=list)
    body_parts: list[str] = field(default_factory=list)
    num_local_seq: int = 0

    @property
    def stem(self) -> str:
        return self.path.stem

    def bone_name(self, index: int) -> str:
        return self.bones[index].name if 0 <= index < len(self.bones) else f"bone{index}"


def _cstr(buf: bytes, off: int) -> str:
    if off <= 0 or off >= len(buf):
        return ""
    end = buf.find(b"\x00", off)
    if end < 0:
        end = len(buf)
    return buf[off:end].decode("ascii", "replace")


def _bones_valid(buf: bytes, index: int, count: int, stride: int) -> bool:
    """A wrong stride desyncs immediately: names stop resolving and parents
    leave the valid range."""
    if index + count * stride > len(buf):
        return False
    for i in range(count):
        off = index + i * stride
        sznameindex, parent = struct.unpack_from("<ii", buf, off)
        name_at = off + sznameindex
        if sznameindex <= 0 or not (0 < name_at < len(buf)):
            return False
        if not (-1 <= parent < count) or parent >= i:
            return False
        name = _cstr(buf, name_at)
        if not name or not all(32 <= ord(c) < 127 for c in name):
            return False
    return True


def _detect_bone_stride(buf: bytes, index: int, count: int) -> int:
    if count == 0:
        return BONE_STRIDE
    for stride in (BONE_STRIDE, 212, 220):
        if _bones_valid(buf, index, count, stride):
            return stride
    raise MdlError("could not determine mstudiobone_t stride")


def read(path: str | Path) -> Mdl:
    path = Path(path)
    buf = path.read_bytes()
    if len(buf) < 408:
        raise MdlError(f"{path.name}: too small to be an MDL")

    ident, version, checksum, raw_name, _length = struct.unpack_from(HDR, buf, 0)
    if ident != b"IDST":
        raise MdlError(f"{path.name}: not an MDL (ident {ident!r})")
    if version != 49:
        raise MdlError(f"{path.name}: unsupported MDL version {version}")

    eye = struct.unpack_from("<3f", buf, 80)
    illum = struct.unpack_from("<3f", buf, 92)
    hull_min = struct.unpack_from("<3f", buf, 104)
    hull_max = struct.unpack_from("<3f", buf, 116)
    view_min = struct.unpack_from("<3f", buf, 128)
    view_max = struct.unpack_from("<3f", buf, 140)
    flags = struct.unpack_from("<i", buf, 152)[0]
    numbones, boneindex = struct.unpack_from("<ii", buf, 156)
    numhbsets, hbsetindex = struct.unpack_from("<ii", buf, 172)
    num_local_seq = struct.unpack_from("<i", buf, 188)[0]
    numtex, texindex = struct.unpack_from("<ii", buf, 204)
    numcd, cdindex = struct.unpack_from("<ii", buf, 212)
    numbodyparts, bodypartindex = struct.unpack_from("<ii", buf, 232)
    numatt, attindex = struct.unpack_from("<ii", buf, 240)
    surfacepropindex = struct.unpack_from("<i", buf, 308)[0]
    mass = struct.unpack_from("<f", buf, 328)[0]
    contents = struct.unpack_from("<i", buf, 332)[0]
    numinclude, includeindex = struct.unpack_from("<ii", buf, 336)

    stride = _detect_bone_stride(buf, boneindex, numbones)
    bones: list[Bone] = []
    for i in range(numbones):
        off = boneindex + i * stride
        sznameindex, parent = struct.unpack_from("<ii", buf, off)
        pos = struct.unpack_from("<3f", buf, off + BONE_POS)
        quat = struct.unpack_from("<4f", buf, off + BONE_QUAT)
        rot = struct.unpack_from("<3f", buf, off + BONE_ROT)
        pose_to_bone = struct.unpack_from("<12f", buf, off + BONE_POSE_TO_BONE)
        bone_flags = struct.unpack_from("<i", buf, off + BONE_FLAGS)[0]
        surfidx, bone_contents = struct.unpack_from("<ii", buf, off + BONE_SURFACEPROP)
        bones.append(
            Bone(
                index=i,
                name=_cstr(buf, off + sznameindex),
                parent=parent,
                pos=pos,
                quat=quat,
                rot=rot,
                pose_to_bone=pose_to_bone,
                surfaceprop=_cstr(buf, off + surfidx) if surfidx else "",
                contents=bone_contents,
                flags=bone_flags,
            )
        )

    hitbox_sets: list[HitBoxSet] = []
    for s in range(numhbsets):
        soff = hbsetindex + s * HBOXSET_STRIDE
        sznameindex, numhb, hbindex = struct.unpack_from("<iii", buf, soff)
        boxes: list[HitBox] = []
        for h in range(numhb):
            hoff = soff + hbindex + h * BBOX_STRIDE
            bone, group = struct.unpack_from("<ii", buf, hoff)
            bbmin = struct.unpack_from("<3f", buf, hoff + 8)
            bbmax = struct.unpack_from("<3f", buf, hoff + 20)
            namefield = struct.unpack_from("<i", buf, hoff + 32)[0]
            boxes.append(
                HitBox(
                    bone=bone,
                    group=group,
                    bbmin=bbmin,
                    bbmax=bbmax,
                    name=_cstr(buf, hoff + namefield) if namefield else "",
                )
            )
        hitbox_sets.append(HitBoxSet(name=_cstr(buf, soff + sznameindex), boxes=boxes))

    attachments: list[Attachment] = []
    for i in range(numatt):
        off = attindex + i * ATTACHMENT_STRIDE
        sznameindex, att_flags, localbone = struct.unpack_from("<iii", buf, off)
        matrix = struct.unpack_from("<12f", buf, off + 12)
        attachments.append(
            Attachment(
                name=_cstr(buf, off + sznameindex),
                flags=att_flags,
                bone=localbone,
                matrix=matrix,
            )
        )

    textures = []
    for i in range(numtex):
        off = texindex + i * TEXTURE_STRIDE
        sznameindex = struct.unpack_from("<i", buf, off)[0]
        textures.append(_cstr(buf, off + sznameindex))

    cdmaterials = []
    for i in range(numcd):
        off = struct.unpack_from("<i", buf, cdindex + 4 * i)[0]
        value = _cstr(buf, off)
        if value:
            cdmaterials.append(value)

    include_models = []
    for i in range(numinclude):
        off = includeindex + i * MODELGROUP_STRIDE
        _lbl, sznameindex = struct.unpack_from("<ii", buf, off)
        value = _cstr(buf, off + sznameindex)
        if value and value not in include_models:
            include_models.append(value)

    body_parts = []
    for i in range(numbodyparts):
        off = bodypartindex + i * BODYPART_STRIDE
        sznameindex = struct.unpack_from("<i", buf, off)[0]
        body_parts.append(_cstr(buf, off + sznameindex))

    return Mdl(
        path=path,
        version=version,
        checksum=checksum,
        internal_name=_cstr(buf, 12) or raw_name.split(b"\x00")[0].decode("ascii", "replace"),
        flags=flags,
        eye_position=eye,
        illum_position=illum,
        hull_min=hull_min,
        hull_max=hull_max,
        view_bbmin=view_min,
        view_bbmax=view_max,
        mass=mass,
        contents=contents,
        surfaceprop=_cstr(buf, surfacepropindex) or "flesh",
        bones=bones,
        hitbox_sets=hitbox_sets,
        attachments=attachments,
        textures=textures,
        cdmaterials=cdmaterials,
        include_models=include_models,
        body_parts=body_parts,
        num_local_seq=num_local_seq,
    )


def has_geometry(mdl_path: Path) -> bool:
    """Animation-only models ship no .vvd, so there is nothing to recolour."""
    return mdl_path.with_suffix(".vvd").exists()
