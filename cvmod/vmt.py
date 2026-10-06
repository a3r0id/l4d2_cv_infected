"""VMT (KeyValues) parsing, `patch` resolution and writing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import config

Pair = tuple[str, "str | list"]

MAX_PATCH_DEPTH = 8


class VmtError(Exception):
    pass


@dataclass
class Material:
    """A VMT flattened down to a shader plus scalar parameters."""

    shader: str
    params: dict[str, str] = field(default_factory=dict)
    include_chain: list[str] = field(default_factory=list)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.params.get(key.lower(), default)

    def truthy(self, key: str) -> bool:
        value = self.get(key)
        return value is not None and value.strip().strip('"') not in ("", "0")


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
        elif c == "{" or c == "}":
            tokens.append(c)
            i += 1
        elif c == '"':
            i += 1
            start = i
            while i < n and text[i] != '"':
                i += 1
            tokens.append(text[start:i])
            i += 1
        else:
            start = i
            while i < n and text[i] not in ' \t\r\n"{}':
                i += 1
            tokens.append(text[start:i])
    return tokens


def _parse_block(tokens: list[str], pos: int) -> tuple[list[Pair], int]:
    pairs: list[Pair] = []
    while pos < len(tokens):
        tok = tokens[pos]
        if tok == "}":
            return pairs, pos + 1
        if tok == "{":
            # Stray block with no key; skip it.
            _, pos = _parse_block(tokens, pos + 1)
            continue
        key = tok
        pos += 1
        if pos >= len(tokens):
            break
        if tokens[pos] == "{":
            block, pos = _parse_block(tokens, pos + 1)
            pairs.append((key, block))
        else:
            pairs.append((key, tokens[pos]))
            pos += 1
    return pairs, pos


def parse_text(text: str) -> tuple[str, list[Pair]]:
    """Return the root shader name and its key/value pairs."""
    tokens = _tokenize(text)
    pos = 0
    while pos < len(tokens) and tokens[pos] in ("{", "}"):
        pos += 1
    if pos >= len(tokens):
        raise VmtError("empty VMT")
    shader = tokens[pos]
    pos += 1
    if pos < len(tokens) and tokens[pos] == "{":
        body, _ = _parse_block(tokens, pos + 1)
    else:
        body = []
    return shader, body


def _scalars(pairs: list[Pair]) -> dict[str, str]:
    return {k.lower(): v for k, v in pairs if isinstance(v, str)}


def _blocks(pairs: list[Pair], name: str) -> list[list[Pair]]:
    return [v for k, v in pairs if isinstance(v, list) and k.lower() == name]


def resolve_include_path(include: str) -> Path:
    rel = include.replace("\\", "/").strip().lstrip("/")
    low = rel.lower()
    if low.startswith("materials/"):
        rel = rel[len("materials/"):]
    path = config.SRC_MATERIALS / rel
    if not path.suffix:
        path = path.with_suffix(".vmt")
    return path


def resolve(path: Path, _depth: int = 0) -> Material:
    """Read a VMT and flatten any `patch` chain into concrete parameters."""
    if _depth > MAX_PATCH_DEPTH:
        raise VmtError(f"patch chain too deep at {path}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise VmtError(f"cannot read {path}: {exc}") from exc

    shader, body = parse_text(text)
    if shader.lower() != "patch":
        return Material(shader=shader, params=_scalars(body))

    scalars = _scalars(body)
    include = scalars.get("include")
    if not include:
        raise VmtError(f"{path}: patch without include")

    base_path = resolve_include_path(include)
    if not base_path.exists():
        raise VmtError(f"{path}: include target missing: {include}")

    base = resolve(base_path, _depth + 1)
    merged = dict(base.params)
    for section in ("insert", "replace"):
        for block in _blocks(body, section):
            merged.update(_scalars(block))

    return Material(
        shader=base.shader,
        params=merged,
        include_chain=[include, *base.include_chain],
    )


def write(path: Path, shader: str, params: dict[str, str]) -> str:
    """Serialise a VMT. Returns the text written."""
    width = max((len(k) for k in params), default=0)
    lines = [shader, "{"]
    for key, value in params.items():
        text_value = str(value)
        if not (text_value.startswith('"') and text_value.endswith('"')):
            text_value = f'"{text_value}"'
        lines.append(f"\t{key.ljust(width)} {text_value}")
    lines.append("}")
    lines.append("")
    text = "\n".join(lines)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text
