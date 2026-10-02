"""Input-hash semantics of ``manifest.py`` (INV-M10 rules).

The server's loader (``modules._01_map.hashing``) must compute the same
``inputs_sha256`` the pipeline writes: ``source/map.svg`` is hashed over
raw bytes (``.gitattributes`` pins it ``-text`` — its CRLFs are part of
the checksum), while ``boundary``/``overrides``/``ids_lock`` are hashed
after CRLF -> LF normalisation so a Windows checkout stays identical.

These tests pin that contract so a future refactor cannot silently split
the two implementations.
"""
from __future__ import annotations

import hashlib

from tools.map_pipeline.manifest import (
    build_inputs_sha256,
    file_sha256,
    text_sha256,
)


def test_text_sha256_crlf_lf_equivalent(tmp_path):
    """Same text with CRLF and LF line endings gives equal hashes."""
    body = "a: 1\nb: два\n"
    lf = tmp_path / "lf.yaml"
    crlf = tmp_path / "crlf.yaml"
    lf.write_bytes(body.encode("utf-8"))
    crlf.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))

    assert text_sha256(lf) == text_sha256(crlf)
    assert text_sha256(lf) == hashlib.sha256(
        body.encode("utf-8")
    ).hexdigest()


def test_file_sha256_is_raw_bytes(tmp_path):
    """``file_sha256`` (the ``source`` rule) never normalises: the same
    text with CRLF instead of LF hashes DIFFERENTLY."""
    body = "<svg>x</svg>\n"
    lf = tmp_path / "lf.svg"
    crlf = tmp_path / "crlf.svg"
    lf.write_bytes(body.encode("utf-8"))
    crlf.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))

    assert file_sha256(lf) == hashlib.sha256(
        body.encode("utf-8")
    ).hexdigest()
    assert file_sha256(crlf) != file_sha256(lf)


def test_build_inputs_sha256_rules(tmp_path):
    """``build_inputs_sha256``: raw for source, CRLF->LF for the rest."""
    src = tmp_path / "map.svg"
    boundary = tmp_path / "boundary.yaml"
    overrides = tmp_path / "overrides.yaml"
    src.write_bytes(b"<svg/>\r\n")
    boundary.write_bytes(b"a: 1\r\n")
    overrides.write_bytes(b"b: 2\r\n")
    lock_text = '{"version": 1, "ids": {}}\n'

    inputs = build_inputs_sha256(src, boundary, overrides, lock_text)

    assert inputs["source"] == hashlib.sha256(b"<svg/>\r\n").hexdigest()
    assert inputs["boundary"] == hashlib.sha256(b"a: 1\n").hexdigest()
    assert inputs["overrides"] == hashlib.sha256(b"b: 2\n").hexdigest()
    assert inputs["ids_lock"] == hashlib.sha256(
        lock_text.encode("utf-8")
    ).hexdigest()
