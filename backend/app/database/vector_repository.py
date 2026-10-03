"""Chunk storage + similarity search. user_id is a mandatory filter on every read."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np

from app.database.db import Database, get_db
from app.models.resource_models import ContentChunk, ContentType

_CHUNK_COLS = (
    "chunk_id", "user_id", "course_id", "resource_id", "lecture_id", "content_type", "heading",
    "module", "week", "resource_title", "text", "page_number", "page_end", "start_time", "end_time",
    "source_url", "metadata", "embedding",
)


@dataclass
class ChunkFilter:
    user_id: str  # required: the authenticated student
    course_ids: Optional[Sequence[str]] = None
    weeks: Optional[Sequence[int]] = None
    content_types: Optional[Sequence[str]] = None
    resource_ids: Optional[Sequence[str]] = None
    lecture_ids: Optional[Sequence[str]] = None

    def sql(self) -> tuple[str, list[Any]]:
        if not self.user_id:
            raise ValueError("user_id is required for every chunk query")
        clauses, params = ["user_id = ?"], [str(self.user_id)]
        for col, vals in (
            ("course_id", self.course_ids),
            ("week", self.weeks),
            ("content_type", self.content_types),
            ("resource_id", self.resource_ids),
            ("lecture_id", self.lecture_ids),
        ):
            if vals is not None:
                vals = list(vals)
                if not vals:
                    return "1 = 0", []
                clauses.append(f"{col} IN ({', '.join('?' * len(vals))})")
                params.extend(str(v) if col != "week" else int(v) for v in vals)
        return " AND ".join(clauses), params


@dataclass
class ScoredChunk:
    chunk: ContentChunk
    score: float
    signals: dict[str, float] = field(default_factory=dict)


class VectorRepository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    def _row_to_chunk(self, r: dict, with_embedding: bool = False) -> ContentChunk:
        emb = self.db.load_vector(r.get("embedding")) if with_embedding else None
        return ContentChunk(
            chunk_id=r["chunk_id"],
            user_id=r["user_id"],
            course_id=r["course_id"],
            resource_id=r["resource_id"],
            lecture_id=r["lecture_id"],
            content_type=ContentType(r["content_type"]),
            heading=r["heading"],
            module=r["module"],
            week=r["week"],
            resource_title=r["resource_title"],
            text=r["text"],
            page_number=r["page_number"],
            page_end=r["page_end"],
            start_time=r["start_time"],
            end_time=r["end_time"],
            source_url=r["source_url"],
            metadata=self.db.load_json(r["metadata"]),
            embedding=emb.tolist() if emb is not None else None,
        )

    def replace_resource_chunks(self, user_id: str, resource_id: str, chunks: list[ContentChunk]) -> None:
        for c in chunks:
            if c.user_id != str(user_id) or c.resource_id != resource_id:
                raise ValueError("chunk ownership/provenance mismatch")
        owned = self.db.fetchone(
            "SELECT 1 AS ok FROM lecture_resources WHERE user_id = ? AND resource_id = ?", (str(user_id), resource_id)
        )
        if not owned:
            raise PermissionError("resource does not belong to this user")
        self.db.execute(
            "DELETE FROM content_chunks WHERE user_id = ? AND resource_id = ?", (str(user_id), resource_id)
        )
        self.db.executemany(
            f"INSERT INTO content_chunks ({', '.join(_CHUNK_COLS)}) VALUES ({', '.join('?' * len(_CHUNK_COLS))})",
            [
                (
                    c.chunk_id, c.user_id, c.course_id, c.resource_id, c.lecture_id, c.content_type.value,
                    c.heading, c.module, c.week, c.resource_title, c.text, c.page_number, c.page_end,
                    c.start_time, c.end_time, c.source_url, self.db.json(c.metadata),
                    self.db.vector(c.embedding),
                )
                for c in chunks
            ],
        )

    def update_metadata(self, user_id: str, chunk_id: str, metadata: dict) -> None:
        self.db.execute(
            "UPDATE content_chunks SET metadata = ? WHERE user_id = ? AND chunk_id = ?",
            (self.db.json(metadata), str(user_id), chunk_id),
        )

    def get_chunks(self, user_id: str, chunk_ids: Sequence[str]) -> list[ContentChunk]:
        ids = list(dict.fromkeys(chunk_ids))
        if not ids:
            return []
        rows = self.db.fetchall(
            f"SELECT * FROM content_chunks WHERE user_id = ? AND chunk_id IN ({', '.join('?' * len(ids))})",
            [str(user_id), *ids],
        )
        by_id = {r["chunk_id"]: self._row_to_chunk(r) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def list_chunks(self, flt: ChunkFilter, with_embedding: bool = False) -> list[ContentChunk]:
        where, params = flt.sql()
        rows = self.db.fetchall(
            f"SELECT * FROM content_chunks WHERE {where} ORDER BY week, resource_id, page_number, start_time",
            params,
        )
        return [self._row_to_chunk(r, with_embedding) for r in rows]

    # ------------------------------------------------------------------ search
    def vector_search(self, flt: ChunkFilter, query_vec: Sequence[float], k: int = 8) -> list[ScoredChunk]:
        where, params = flt.sql()
        if self.db.is_postgres:
            rows = self.db.fetchall(
                f"SELECT *, 1 - (embedding <=> ?) AS score FROM content_chunks "
                f"WHERE {where} AND embedding IS NOT NULL ORDER BY embedding <=> ? LIMIT ?",
                [self.db.vector(query_vec), *params, self.db.vector(query_vec), k],
            )
            return [ScoredChunk(self._row_to_chunk(r), float(r["score"]), {"vector": float(r["score"])}) for r in rows]

        rows = self.db.fetchall(
            f"SELECT chunk_id, embedding FROM content_chunks WHERE {where} AND embedding IS NOT NULL", params
        )
        if not rows:
            return []
        mat = np.stack([self.db.load_vector(r["embedding"]) for r in rows])
        q = np.asarray(query_vec, dtype=np.float32)
        q = q / (np.linalg.norm(q) or 1.0)
        norms = np.linalg.norm(mat, axis=1)
        norms[norms == 0] = 1.0
        scores = (mat @ q) / norms
        top = np.argsort(-scores)[:k]
        chunks = {c.chunk_id: c for c in self.get_chunks(flt.user_id, [rows[i]["chunk_id"] for i in top])}
        return [
            ScoredChunk(chunks[rows[i]["chunk_id"]], float(scores[i]), {"vector": float(scores[i])})
            for i in top
            if rows[i]["chunk_id"] in chunks
        ]

    def keyword_search(self, flt: ChunkFilter, terms: Sequence[str], k: int = 20) -> list[ScoredChunk]:
        """Lexical recall for exact technical terms (e.g. 'ReLU') that embeddings can blur."""
        terms = [t.lower() for t in terms if len(t) >= 2][:8]
        if not terms:
            return []
        where, params = flt.sql()
        like = " OR ".join("LOWER(text) LIKE ?" for _ in terms)
        rows = self.db.fetchall(
            f"SELECT * FROM content_chunks WHERE {where} AND ({like})",
            [*params, *[f"%{t}%" for t in terms]],
        )
        scored = []
        for r in rows:
            text = (r["text"] + " " + (r["heading"] or "")).lower()
            hits = sum(len(re.findall(rf"\b{re.escape(t)}\b", text)) for t in terms)
            in_heading = sum(t in (r["heading"] or "").lower() for t in terms)
            covered = sum(1 for t in terms if t in text) / len(terms)
            score = covered * (1 + 0.15 * min(hits, 10) + 0.5 * in_heading)
            if score > 0:
                scored.append(ScoredChunk(self._row_to_chunk(r), score, {"keyword": score}))
        scored.sort(key=lambda s: -s.score)
        return scored[:k]
