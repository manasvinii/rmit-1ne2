"""Deterministic identifiers so re-ingestion updates rows instead of duplicating them."""

from __future__ import annotations

import hashlib
from pathlib import Path


def _h(*parts: object, n: int = 20) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def make_resource_id(user_id: str, course_id: str, provider: str, source_key: str) -> str:
    return "res_" + _h(user_id, course_id, provider, source_key)


def make_chunk_id(resource_id: str, kind: str, locator: object) -> str:
    return "chk_" + _h(resource_id, kind, locator)


def make_node_id(user_id: str, course_id: str, node_type: str, node_key: str) -> str:
    return "n_" + _h(user_id, course_id, node_type, node_key)


def make_edge_id(user_id: str, course_id: str, source: str, relation: str, target: str) -> str:
    return "e_" + _h(user_id, course_id, source, relation, target)


def make_id(prefix: str, *parts: object) -> str:
    return f"{prefix}_" + _h(*parts)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
