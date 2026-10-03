"""Ingest lecture files that are already on the server (LOCAL_CONTENT_DIR) into the student's space."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.core.auth import CurrentUser
from app.core.config import get_settings
from app.database.resource_repository import ResourceRepository
from app.models.schemas import IngestLocalRequest
from app.services.ingestion_service import IngestionService
from app.services.providers import LocalFolderProvider

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ingestion", tags=["ingestion"])


def _resolve_dir(sub: str | None) -> Path:
    root_raw = get_settings().local_content_dir
    if not root_raw:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "LOCAL_CONTENT_DIR is not configured")
    root = Path(root_raw).resolve()
    target = (root / sub).resolve() if sub else root
    if root != target and root not in target.parents:  # path traversal guard
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid subdirectory")
    if not target.is_dir():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Content folder not found")
    return target


def _run(user_id: str, body: IngestLocalRequest, folder: Path) -> None:
    try:
        resources = LocalFolderProvider(folder).discover(user_id, body.course_id)
        report = IngestionService().ingest(resources, force=body.force, build_graph=body.build_graph, use_llm=body.use_llm)
        log.info("Local ingestion finished: %s", {k: len(v) if isinstance(v, (list, dict)) else v for k, v in report.as_dict().items() if k != "graph"})
    except Exception:
        log.exception("Local ingestion failed")


@router.post("/local", status_code=202)
def ingest_local(body: IngestLocalRequest, background: BackgroundTasks, user_id: str = CurrentUser):
    folder = _resolve_dir(body.subdirectory)
    discovered = LocalFolderProvider(folder).discover(user_id, body.course_id)
    background.add_task(_run, user_id, body, folder)
    return {"accepted": True, "resources": [{"title": r.title, "type": r.resource_type.value, "week": r.week} for r in discovered]}


@router.get("/status")
def ingestion_status(user_id: str = CurrentUser):
    repo = ResourceRepository()
    return {
        "resources": [
            {"title": r.title, "course_id": r.canvas_course_id, "type": r.resource_type.value, "week": r.week,
             "status": r.status.value, "error": r.metadata.get("error")}
            for r in repo.list(user_id)
        ],
        "jobs": repo.list_jobs(user_id, limit=20),
    }
