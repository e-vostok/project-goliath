"""
Input-file hashing rules for INV-M10 and the Spec 3.6 geometry version.

One table of per-file rules — no scattered if-statements:

- ``source`` (``source/map.svg``): raw SHA-256 of the bytes, untouched.
  The file is pinned ``-text`` in ``.gitattributes`` — *"Окончания CRLF —
  часть контрольной суммы, поэтому для этого файла отключена любая
  текстовая нормализация"* — its CRLF pairs are part of the committed
  checksum and git will never line-ending-convert it on checkout.
- ``boundary``, ``overrides``, ``ids_lock``: :func:`normalized_sha256`
  (every ``\\r\\n`` folded to ``\\n``), so a Windows worktree
  (``core.autocrlf=true``) hashes identically to an LF checkout.

These rules mirror the pipeline's own computation exactly
(``file_sha256`` for the source, ``text_sha256`` for the text inputs, the
canonical LF text for the generated lock file), so
``manifest.inputs_sha256`` verifies against the real ``data/map/`` on any
platform.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

HASH_RAW = "raw_sha256"
HASH_NORMALIZED = "normalized_sha256"

# INV-M10 per-file rules (amended TZ §3.2/§3.3): the ONLY mapping from an
# inputs_sha256 key to its hash rule. Keys match manifest.inputs_sha256.
INPUT_HASH_RULES: dict[str, str] = {
    "source": HASH_RAW,
    "boundary": HASH_NORMALIZED,
    "overrides": HASH_NORMALIZED,
    "ids_lock": HASH_NORMALIZED,
}

_CHUNK = 1 << 20  # 1 MiB


def raw_sha256(path: Path) -> str:
    """SHA-256 of the file bytes exactly as stored."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def normalized_sha256(path: Path) -> str:
    """
    SHA-256 of the file bytes with every ``\\r\\n`` replaced by ``\\n``.

    Reads in chunks; a ``\\r`` ending a chunk is carried over so a CRLF
    pair split across the chunk boundary is still normalised.
    """
    h = hashlib.sha256()
    carry = b""
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            data = carry + chunk
            carry = b""
            if data.endswith(b"\r"):
                carry = b"\r"
                data = data[:-1]
            h.update(data.replace(b"\r\n", b"\n"))
    h.update(carry)
    return h.hexdigest()


def input_sha256(path: Path, rule: str) -> str:
    """Hash ``path`` under one of the ``HASH_*`` rules."""
    if rule == HASH_RAW:
        return raw_sha256(path)
    if rule == HASH_NORMALIZED:
        return normalized_sha256(path)
    raise ValueError(f"unknown input hash rule {rule!r}")


def geometry_version(
    outside: str, paths: Mapping[str, str], sea_water: str
) -> str:
    """
    Spec 3.6: ``sha256(canon(G))[:12]`` where ``canon`` is the JSON of
    ``{"outside": ..., "paths": ..., "sea_water": ...}`` (no ``version``
    field) with sorted keys, tight ``,``/``:`` separators, encoded UTF-8.
    """
    canon = json.dumps(
        {
            "outside": outside,
            "paths": dict(paths),
            "sea_water": sea_water,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def borders_version(
    geometry_ver: str, pairs: Mapping[str, str], coasts: Mapping[str, str]
) -> str:
    """
    Spec 3.6 with the geometry version as an extra input (map2_1B):
    ``sha256(canon(B))[:12]`` where ``canon`` is the JSON of the
    ``borders.json`` body without ``version`` plus ``geometry_version``
    — the borders version changes whenever the geometry version does.
    """
    canon = json.dumps(
        {
            "coasts": dict(coasts),
            "geometry_version": geometry_ver,
            "pairs": dict(pairs),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]
