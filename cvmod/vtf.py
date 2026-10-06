"""VTF reading and writing, scoped to what the pipeline needs.

Writes VTF 7.2 BGRA8888 with a full mip chain and a DXT1 thumbnail so the
engine never has to synthesise anything. Also decodes the alpha channel out of
existing DXT1/DXT3/DXT5 textures, which is how alpha-tested hair keeps its
cutout while its colour is replaced.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

# L4D2 ships 7.4 almost exclusively, and Valve's own tools reject the older
# resource-directory-free layouts, so write 7.4.
VERSION = (7, 4)
BASE_HEADER_SIZE = 80
RESOURCE_COUNT = 2  # low-res thumbnail + high-res image
HEADER_SIZE = BASE_HEADER_SIZE + RESOURCE_COUNT * 8
RESOURCE_LOWRES = b"\x01\x00\x00"
IMAGE_FORMAT_RGBA8888 = 0
IMAGE_FORMAT_ABGR8888 = 1
IMAGE_FORMAT_RGB888 = 2
IMAGE_FORMAT_BGR888 = 3
IMAGE_FORMAT_ARGB8888 = 11
IMAGE_FORMAT_BGRA8888 = 12
IMAGE_FORMAT_DXT1 = 13
IMAGE_FORMAT_DXT3 = 14
IMAGE_FORMAT_DXT5 = 15
IMAGE_FORMAT_DXT1_ONEBITALPHA = 16

RESOURCE_HIGHRES = b"\x30\x00\x00"

FLAG_POINTSAMPLE = 0x00000001
FLAG_TRILINEAR = 0x00000002
FLAG_CLAMPS = 0x00000004
FLAG_CLAMPT = 0x00000008
FLAG_NOMIP = 0x00000100
FLAG_NOLOD = 0x00000200
FLAG_ONEBITALPHA = 0x00001000
FLAG_EIGHTBITALPHA = 0x00002000
FLAG_ENVMAP = 0x00004000

DEFAULT_FLAGS = FLAG_POINTSAMPLE | FLAG_CLAMPS | FLAG_CLAMPT | FLAG_EIGHTBITALPHA
# Hair cards tile their UVs, so no clamping, and keep bilinear for clean edges.
MASK_FLAGS = FLAG_EIGHTBITALPHA
DEFAULT_SIZE = 16
THUMBNAIL_SIZE = 4


def _rgb565(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _dxt1_solid_block(r: int, g: int, b: int) -> bytes:
    """One 4x4 DXT1 block where every texel is the given colour."""
    c = _rgb565(r, g, b)
    return struct.pack("<HHI", c, c, 0)


def _mip_sizes(size: int) -> list[int]:
    sizes = []
    s = size
    while s >= 1:
        sizes.append(s)
        if s == 1:
            break
        s //= 2
    return sizes


def _assemble(
    width: int,
    height: int,
    flags: int,
    color: tuple[int, int, int],
    mips_smallest_first: list[bytes],
) -> bytes:
    """Build a VTF 7.4 file laid out exactly like the ones the game ships."""
    r, g, b = color
    thumb_blocks = (THUMBNAIL_SIZE // 4) ** 2
    lowres = _dxt1_solid_block(r, g, b) * thumb_blocks

    header = bytearray(BASE_HEADER_SIZE + RESOURCE_COUNT * 8)
    struct.pack_into("<4sIII", header, 0, b"VTF\x00", VERSION[0], VERSION[1], HEADER_SIZE)
    struct.pack_into("<HH", header, 16, width, height)
    struct.pack_into("<I", header, 20, flags)
    struct.pack_into("<HH", header, 24, 1, 0)  # frames, firstFrame
    struct.pack_into("<3f", header, 32, r / 255.0, g / 255.0, b / 255.0)
    struct.pack_into("<f", header, 48, 1.0)  # bumpmapScale
    struct.pack_into("<I", header, 52, IMAGE_FORMAT_BGRA8888)
    struct.pack_into("<B", header, 56, len(mips_smallest_first))
    struct.pack_into("<I", header, 57, IMAGE_FORMAT_DXT1)
    struct.pack_into("<BB", header, 61, THUMBNAIL_SIZE, THUMBNAIL_SIZE)
    struct.pack_into("<H", header, 63, 1)  # depth
    struct.pack_into("<I", header, 68, RESOURCE_COUNT)
    struct.pack_into("<3sBI", header, 80, RESOURCE_LOWRES, 0, HEADER_SIZE)
    struct.pack_into("<3sBI", header, 88, RESOURCE_HIGHRES, 0, HEADER_SIZE + len(lowres))

    out = bytearray(header)
    out += lowres
    for level in mips_smallest_first:
        out += level
    return bytes(out)


def build(color: tuple[int, int, int], alpha: int = 255, size: int = DEFAULT_SIZE) -> bytes:
    r, g, b = (max(0, min(255, int(v))) for v in color)
    a = max(0, min(255, int(alpha)))
    texel = bytes((b, g, r, a))  # BGRA8888
    mips = [texel * (mip * mip) for mip in reversed(_mip_sizes(size))]
    return _assemble(size, size, DEFAULT_FLAGS, (r, g, b), mips)


def write(path: Path, color: tuple[int, int, int], alpha: int = 255, size: int = DEFAULT_SIZE) -> bytes:
    data = build(color, alpha=alpha, size=size)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

_BLOCK_BYTES = {
    IMAGE_FORMAT_DXT1: 8,
    IMAGE_FORMAT_DXT1_ONEBITALPHA: 8,
    IMAGE_FORMAT_DXT3: 16,
    IMAGE_FORMAT_DXT5: 16,
}
_PIXEL_BYTES = {
    IMAGE_FORMAT_RGBA8888: 4,
    IMAGE_FORMAT_ABGR8888: 4,
    IMAGE_FORMAT_ARGB8888: 4,
    IMAGE_FORMAT_BGRA8888: 4,
    IMAGE_FORMAT_RGB888: 3,
    IMAGE_FORMAT_BGR888: 3,
}
_ALPHA_BYTE = {
    IMAGE_FORMAT_RGBA8888: 3,
    IMAGE_FORMAT_BGRA8888: 3,
    IMAGE_FORMAT_ABGR8888: 0,
    IMAGE_FORMAT_ARGB8888: 0,
}


class VtfError(Exception):
    pass


def image_size(fmt: int, w: int, h: int) -> int:
    if fmt in _BLOCK_BYTES:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * _BLOCK_BYTES[fmt]
    if fmt in _PIXEL_BYTES:
        return w * h * _PIXEL_BYTES[fmt]
    raise VtfError(f"unsupported image format {fmt}")


def _parse_header(buf: bytes) -> dict:
    sig, vmaj, vmin, header_size = struct.unpack_from("<4sIII", buf, 0)
    if sig != b"VTF\x00":
        raise VtfError("not a VTF")
    w, h = struct.unpack_from("<HH", buf, 16)
    flags = struct.unpack_from("<I", buf, 20)[0]
    frames = struct.unpack_from("<H", buf, 24)[0]
    fmt = struct.unpack_from("<I", buf, 52)[0]
    mips = buf[56]
    low_fmt = struct.unpack_from("<I", buf, 57)[0]
    low_w, low_h = buf[61], buf[62]
    version = (vmaj, vmin)
    depth = struct.unpack_from("<H", buf, 63)[0] if version >= (7, 2) else 1

    data_offset: int | None = None
    if version >= (7, 3):
        num_resources = struct.unpack_from("<I", buf, 68)[0]
        for i in range(num_resources):
            off = 80 + i * 8
            tag = buf[off : off + 3]
            res_offset = struct.unpack_from("<I", buf, off + 4)[0]
            if tag == RESOURCE_HIGHRES:
                data_offset = res_offset
                break
    if data_offset is None:
        data_offset = header_size
        if low_fmt != 0xFFFFFFFF and low_w and low_h:
            data_offset += image_size(low_fmt, low_w, low_h)

    return {
        "version": version,
        "width": w,
        "height": h,
        "flags": flags,
        "frames": max(1, frames),
        "format": fmt,
        "mips": max(1, mips),
        "depth": max(1, depth),
        "data_offset": data_offset,
    }


def _largest_mip_offset(hdr: dict) -> int:
    """VTF stores mips smallest-first, so the base image sits last."""
    offset = hdr["data_offset"]
    faces = 1
    for i in range(hdr["mips"] - 1, 0, -1):
        mw = max(1, hdr["width"] >> i)
        mh = max(1, hdr["height"] >> i)
        offset += image_size(hdr["format"], mw, mh) * hdr["frames"] * faces * hdr["depth"]
    return offset


def _decode_dxt_alpha(data: bytes, fmt: int, w: int, h: int) -> np.ndarray:
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    stride = _BLOCK_BYTES[fmt]
    blocks = np.frombuffer(data[: bw * bh * stride], dtype=np.uint8).reshape(bh, bw, stride)
    out = np.full((bh * 4, bw * 4), 255, dtype=np.uint8)

    if fmt in (IMAGE_FORMAT_DXT1, IMAGE_FORMAT_DXT1_ONEBITALPHA):
        c0 = blocks[:, :, 0].astype(np.uint16) | (blocks[:, :, 1].astype(np.uint16) << 8)
        c1 = blocks[:, :, 2].astype(np.uint16) | (blocks[:, :, 3].astype(np.uint16) << 8)
        bits = np.zeros((bh, bw), dtype=np.uint32)
        for i in range(4):
            bits |= blocks[:, :, 4 + i].astype(np.uint32) << (8 * i)
        punchthrough = c0 <= c1  # DXT1 uses index 3 as transparent in this mode
        for py in range(4):
            for px in range(4):
                idx = (bits >> np.uint32(2 * (py * 4 + px))) & np.uint32(3)
                transparent = punchthrough & (idx == 3)
                out[py::4, px::4] = np.where(transparent, 0, 255).astype(np.uint8)

    elif fmt == IMAGE_FORMAT_DXT3:
        for py in range(4):
            for px in range(4):
                nibble_index = py * 4 + px
                byte = blocks[:, :, nibble_index // 2]
                value = np.where(nibble_index % 2 == 0, byte & 0x0F, byte >> 4)
                out[py::4, px::4] = (value * 17).astype(np.uint8)

    elif fmt == IMAGE_FORMAT_DXT5:
        a0 = blocks[:, :, 0].astype(np.int32)
        a1 = blocks[:, :, 1].astype(np.int32)
        bits = np.zeros((bh, bw), dtype=np.uint64)
        for i in range(6):
            bits |= blocks[:, :, 2 + i].astype(np.uint64) << np.uint64(8 * i)
        wide = a0 > a1
        palette = np.zeros((8, bh, bw), dtype=np.int32)
        palette[0], palette[1] = a0, a1
        for i in range(2, 8):
            k = i - 1
            seven = ((7 - k) * a0 + k * a1) // 7
            five = ((5 - k) * a0 + k * a1) // 5 if k <= 5 else 0
            if i < 6:
                palette[i] = np.where(wide, seven, five)
            elif i == 6:
                palette[i] = np.where(wide, seven, 0)
            else:
                palette[i] = np.where(wide, seven, 255)
        for py in range(4):
            for px in range(4):
                idx = ((bits >> np.uint64(3 * (py * 4 + px))) & np.uint64(7)).astype(np.int32)
                picked = np.take_along_axis(palette, idx[None, :, :], axis=0)[0]
                out[py::4, px::4] = picked.astype(np.uint8)
    else:
        raise VtfError(f"format {fmt} is not block compressed")

    return out[:h, :w]


def read_alpha(path: Path) -> np.ndarray:
    """Return the base mip's alpha channel as a (height, width) uint8 array."""
    buf = path.read_bytes()
    hdr = _parse_header(buf)
    fmt, w, h = hdr["format"], hdr["width"], hdr["height"]
    offset = _largest_mip_offset(hdr)
    size = image_size(fmt, w, h)
    data = buf[offset : offset + size]
    if len(data) < size:
        raise VtfError(f"{path.name}: truncated image data")

    if fmt in _BLOCK_BYTES:
        return _decode_dxt_alpha(data, fmt, w, h)
    if fmt in _ALPHA_BYTE:
        px = _PIXEL_BYTES[fmt]
        arr = np.frombuffer(data, dtype=np.uint8).reshape(h, w, px)
        return arr[:, :, _ALPHA_BYTE[fmt]].copy()
    return np.full((h, w), 255, dtype=np.uint8)


# --------------------------------------------------------------------------
# Masked (flat colour + borrowed alpha) textures
# --------------------------------------------------------------------------


def build_masked(color: tuple[int, int, int], alpha: np.ndarray) -> bytes:
    """Flat colour everywhere, alpha taken from `alpha`, with a full mip chain."""
    r, g, b = (max(0, min(255, int(v))) for v in color)
    h, w = alpha.shape
    if w & (w - 1) or h & (h - 1):
        raise VtfError(f"non power-of-two texture {w}x{h}")

    levels: list[np.ndarray] = [alpha]
    while levels[-1].shape[0] > 1 or levels[-1].shape[1] > 1:
        prev = levels[-1]
        ph, pw = prev.shape
        nh, nw = max(1, ph // 2), max(1, pw // 2)
        # Box filter in float, so partially covered texels fade out smoothly
        # instead of popping between fully opaque and fully clipped.
        resized = prev[: nh * 2, : nw * 2].astype(np.float32).reshape(nh, 2, nw, 2).mean(axis=(1, 3))
        levels.append(resized.round().astype(np.uint8))

    mips: list[bytes] = []
    for level in reversed(levels):  # smallest mip first
        lh, lw = level.shape
        bgra = np.empty((lh, lw, 4), dtype=np.uint8)
        bgra[:, :, 0] = b
        bgra[:, :, 1] = g
        bgra[:, :, 2] = r
        bgra[:, :, 3] = level
        mips.append(bgra.tobytes())

    return _assemble(w, h, MASK_FLAGS, (r, g, b), mips)
