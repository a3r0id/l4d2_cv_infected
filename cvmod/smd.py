"""SMD writing and the bone maths needed to place geometry in the rest pose."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .mdl import Bone


@dataclass
class Vertex:
    bone: int
    pos: tuple[float, float, float]
    normal: tuple[float, float, float]
    uv: tuple[float, float]


@dataclass
class Triangle:
    material: str
    verts: tuple[Vertex, Vertex, Vertex]


def euler_matrix(rx: float, ry: float, rz: float) -> np.ndarray:
    """Source's RadianEuler to rotation matrix.

    `AngleMatrix(RadianEuler)` maps (x, y, z) onto QAngle(pitch=y, yaw=z,
    roll=x) and builds Rz(yaw) @ Ry(pitch) @ Rx(roll).
    """
    sr, cr = np.sin(rx), np.cos(rx)
    sp, cp = np.sin(ry), np.cos(ry)
    sy, cy = np.sin(rz), np.cos(rz)
    return np.array(
        [
            [cp * cy, sr * sp * cy - cr * sy, cr * sp * cy + sr * sy],
            [cp * sy, sr * sp * sy + cr * cy, cr * sp * sy - sr * cy],
            [-sp, sr * cp, cr * cp],
        ],
        dtype=np.float64,
    )


def quat_matrix(q: tuple[float, float, float, float]) -> np.ndarray:
    """Source stores bone quaternions as (x, y, z, w)."""
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def local_matrix(bone: Bone) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = euler_matrix(*bone.rot)
    m[:3, 3] = bone.pos
    return m


def model_matrices(bones: list[Bone]) -> list[np.ndarray]:
    """Rest-pose bone-to-model transforms, composed down the hierarchy."""
    out: list[np.ndarray] = []
    for bone in bones:
        local = local_matrix(bone)
        out.append(local if bone.parent < 0 else out[bone.parent] @ local)
    return out


def matrix_to_qangle(rotation: np.ndarray) -> tuple[float, float, float]:
    """Decompose a rotation into Source's (pitch, yaw, roll), in radians."""
    clamped = max(-1.0, min(1.0, float(rotation[2][0])))
    pitch = math.asin(-clamped)
    if abs(clamped) < 0.9999995:
        yaw = math.atan2(float(rotation[1][0]), float(rotation[0][0]))
        roll = math.atan2(float(rotation[2][1]), float(rotation[2][2]))
    else:  # gimbal lock: yaw and roll collapse onto one axis
        yaw = math.atan2(-float(rotation[0][1]), float(rotation[1][1]))
        roll = 0.0
    return pitch, yaw, roll


def bone_qangle(bone: Bone) -> tuple[float, float, float]:
    """The bone's bind rotation as a QAngle, for `$definebone`.

    The MDL stores a RadianEuler, which the SMD skeleton block accepts
    verbatim. `$definebone` instead reads a QAngle in degrees, so feeding it
    the raw values permutes the skeleton and makes studiomdl realign the mesh
    away from where it belongs.
    """
    return matrix_to_qangle(euler_matrix(*bone.rot))


def euler_vs_quat_error(bones: list[Bone]) -> float:
    """Largest disagreement between a bone's stored Euler and its quaternion.

    A near-zero result confirms the Euler convention above matches the one
    studiomdl will use when it reads the SMD back.
    """
    worst = 0.0
    for bone in bones:
        diff = np.abs(euler_matrix(*bone.rot) - quat_matrix(bone.quat)).max()
        worst = max(worst, float(diff))
    return worst


def write(path: Path, bones: list[Bone], triangles: list[Triangle]) -> str:
    lines: list[str] = ["version 1", "nodes"]
    for bone in bones:
        lines.append(f'{bone.index} "{bone.name}" {bone.parent}')
    lines.append("end")

    lines.append("skeleton")
    lines.append("time 0")
    for bone in bones:
        px, py, pz = bone.pos
        # The SMD skeleton takes the RadianEuler straight from the MDL.
        # $definebone, confusingly, wants the same rotation as a QAngle in
        # degrees instead -- see bone_qangle.
        rx, ry, rz = bone.rot
        lines.append(
            f"{bone.index} {px:.6f} {py:.6f} {pz:.6f} {rx:.6f} {ry:.6f} {rz:.6f}"
        )
    lines.append("end")

    lines.append("triangles")
    for tri in triangles:
        lines.append(tri.material)
        for v in tri.verts:
            x, y, z = v.pos
            nx, ny, nz = v.normal
            u, w = v.uv
            lines.append(
                f"{v.bone} {x:.6f} {y:.6f} {z:.6f} "
                f"{nx:.6f} {ny:.6f} {nz:.6f} {u:.6f} {w:.6f} 1 {v.bone} 1.000000"
            )
    lines.append("end")
    lines.append("")

    text = "\n".join(lines)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text
