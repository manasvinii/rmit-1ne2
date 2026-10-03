"""Persistence for lecture resources, transcript segments and ingestion jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.database.db import Database, get_db
from app.models.resource_models import (
    IngestionStatus,
    LectureResource,
    ResourceType,
    SourceProvider,
    TranscriptSegment,
)
from app.services.resource_ids import make_id

_RES_COLS = (
    "resource_id", "user_id", "course_id", "module_id", "module_name", "title", "resource_type",
    "mime_type", "canvas_url", "download_url", "local_path", "source_provider", "week",
    "lecture_number", "is_external", "content_hash", "source_updated_at", "size_bytes", "status",
    "metadata", "created_at", "updated_at",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResourceRepository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    def _row_to_resource(self, r: dict) -> LectureResource:
        return LectureResource(
            resource_id=r["resource_id"],
            canvas_course_id=r["course_id"],
            user_id=r["user_id"],
            module_id=r["module_id"],
            module_name=r["module_name"],
            title=r["title"],
            resource_type=ResourceType(r["resource_type"]),
            mime_type=r["mime_type"],
            canvas_url=r["canvas_url"],
            download_url=r["download_url"],
            local_path=r["local_path"],
            source_provider=SourceProvider(r["source_provider"]),
            week=r["week"],
            lecture_number=r["lecture_number"],
            is_external=bool(r["is_external"]),
            content_hash=r["content_hash"],
            source_updated_at=r["source_updated_at"],
            size_bytes=r["size_bytes"],
            status=IngestionStatus(r["status"]),
            metadata={**self.db.load_json(r["metadata"]), **({"error": r["error"]} if r.get("error") else {})},
        )

    def get(self, user_id: str, resource_id: str) -> Optional[LectureResource]:
        r = self.db.fetchone(
            "SELECT * FROM lecture_resources WHERE user_id = ? AND resource_id = ?",
            (str(user_id), resource_id),
        )
        return self._row_to_resource(r) if r else None

    def list(self, user_id: str, course_id: Optional[str] = None) -> list[LectureResource]:
        if course_id is None:
            rows = self.db.fetchall(
                "SELECT * FROM lecture_resources WHERE user_id = ? ORDER BY week, title", (str(user_id),)
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM lecture_resources WHERE user_id = ? AND course_id = ? ORDER BY week, title",
                (str(user_id), str(course_id)),
            )
        return [self._row_to_resource(r) for r in rows]

    def delete_course(self, user_id: str, course_id: str) -> int:
        """Remove one student's ingested material for a course (chunks/segments cascade)."""
        n = len(self.list(user_id, course_id))
        self.db.execute("DELETE FROM ingestion_jobs WHERE user_id = ? AND course_id = ?", (str(user_id), str(course_id)))
        self.db.execute("DELETE FROM lecture_resources WHERE user_id = ? AND course_id = ?", (str(user_id), str(course_id)))
        return n

    def delete_resource(self, user_id: str, resource_id: str) -> None:
        self.db.execute("DELETE FROM lecture_resources WHERE user_id = ? AND resource_id = ?", (str(user_id), resource_id))

    def course_ids(self, user_id: str) -> list[str]:
        rows = self.db.fetchall(
            "SELECT DISTINCT course_id FROM lecture_resources WHERE user_id = ?", (str(user_id),)
        )
        return [r["course_id"] for r in rows]

    def upsert(self, res: LectureResource) -> None:
        values: dict[str, Any] = {
            "resource_id": res.resource_id,
            "user_id": res.user_id,
            "course_id": res.canvas_course_id,
            "module_id": res.module_id,
            "module_name": res.module_name,
            "title": res.title,
            "resource_type": res.resource_type.value,
            "mime_type": res.mime_type,
            "canvas_url": res.canvas_url,
            "download_url": res.download_url,
            "local_path": res.local_path,
            "source_provider": res.source_provider.value,
            "week": res.week,
            "lecture_number": res.lecture_number,
            "is_external": res.is_external,
            "content_hash": res.content_hash,
            "source_updated_at": res.source_updated_at,
            "size_bytes": res.size_bytes,
            "status": res.status.value,
            "metadata": self.db.json(res.metadata),
            "created_at": _now(),
            "updated_at": _now(),
        }
        keep = {"resource_id", "created_at", "status", "content_hash"}
        updates = ", ".join(f"{c} = excluded.{c}" for c in _RES_COLS if c not in keep)
        self.db.execute(
            f"INSERT INTO lecture_resources ({', '.join(_RES_COLS)}) "
            f"VALUES ({', '.join('?' * len(_RES_COLS))}) "
            f"ON CONFLICT (resource_id) DO UPDATE SET {updates}",
            [values[c] for c in _RES_COLS],
        )

    def set_status(
        self,
        user_id: str,
        resource_id: str,
        status: IngestionStatus,
        error: Optional[str] = None,
        content_hash: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        sets = ["status = ?", "error = ?", "updated_at = ?"]
        params: list[Any] = [status.value, error, _now()]
        if content_hash is not None:
            sets.append("content_hash = ?")
            params.append(content_hash)
        if metadata is not None:
            sets.append("metadata = ?")
            params.append(self.db.json(metadata))
        self.db.execute(
            f"UPDATE lecture_resources SET {', '.join(sets)} WHERE user_id = ? AND resource_id = ?",
            [*params, str(user_id), resource_id],
        )

    # ------------------------------------------------------------------ transcript segments
    def replace_segments(
        self, user_id: str, course_id: str, resource_id: str, segments: list[TranscriptSegment]
    ) -> None:
        self.db.execute(
            "DELETE FROM lecture_segments WHERE user_id = ? AND resource_id = ?", (str(user_id), resource_id)
        )
        self.db.executemany(
            "INSERT INTO lecture_segments (segment_id, user_id, course_id, resource_id, seq, start_time, "
            "end_time, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (make_id("seg", resource_id, i), str(user_id), str(course_id), resource_id, i,
                 s.start_time, s.end_time, s.text)
                for i, s in enumerate(segments)
            ],
        )

    def get_segments(
        self, user_id: str, resource_id: str, start: Optional[float] = None, end: Optional[float] = None
    ) -> list[dict]:
        sql = "SELECT * FROM lecture_segments WHERE user_id = ? AND resource_id = ?"
        params: list[Any] = [str(user_id), resource_id]
        if start is not None:
            sql += " AND end_time >= ?"
            params.append(start)
        if end is not None:
            sql += " AND start_time <= ?"
            params.append(end)
        return self.db.fetchall(sql + " ORDER BY seq", params)

    # ------------------------------------------------------------------ jobs
    def start_job(self, user_id: str, course_id: str, resource_id: Optional[str], stage: str) -> str:
        job_id = make_id("job", user_id, resource_id, _now())
        self.db.execute(
            "INSERT INTO ingestion_jobs (job_id, user_id, course_id, resource_id, status, stage, stats, "
            "started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, str(user_id), str(course_id), resource_id, IngestionStatus.PROCESSING.value, stage,
             self.db.json({}), _now()),
        )
        return job_id

    def finish_job(
        self, job_id: str, status: IngestionStatus, stats: Optional[dict] = None, error: Optional[str] = None
    ) -> None:
        self.db.execute(
            "UPDATE ingestion_jobs SET status = ?, stats = ?, error = ?, finished_at = ? WHERE job_id = ?",
            (status.value, self.db.json(stats or {}), error, _now(), job_id),
        )

    def list_jobs(self, user_id: str, limit: int = 50) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM ingestion_jobs WHERE user_id = ? ORDER BY started_at DESC LIMIT ?",
            (str(user_id), limit),
        )
        return [{**r, "stats": self.db.load_json(r["stats"])} for r in rows]
