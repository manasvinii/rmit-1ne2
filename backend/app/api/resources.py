"""Lecture resource listing and authorised file access via short-lived signed URLs.

Source cards open in a new browser tab, which cannot send the bearer header, so citations
carry an HMAC signature bound to (user, resource, expiry) instead of the session token.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.core.auth import CurrentUser, authorised_courses
from app.core.config import get_settings
from app.core.security import sign_resource_url, verify_resource_signature
from app.database.graph_repository import GraphRepository
from app.database.resource_repository import ResourceRepository

router = APIRouter(prefix="/resources", tags=["resources"])


def signed_resource_url(user_id: str, resource_id: str, page: Optional[int], start: Optional[float]) -> Optional[str]:
    res = ResourceRepository().get(user_id, resource_id)
    if res is None:
        return None
    if not res.local_path or not Path(res.local_path).is_file():
        return res.canvas_url  # no local copy: fall back to the Canvas page (no page anchor possible)
    exp, sig = sign_resource_url(user_id, resource_id)
    url = f"{get_settings().public_base_url}/resources/{resource_id}/file?" + urlencode({"uid": user_id, "exp": exp, "sig": sig})
    if page:
        url += f"#page={page}"
    elif start is not None:
        url += f"#t={int(start)}"
    return url


@router.get("")
def list_resources(course_id: Optional[str] = None, user_id: str = CurrentUser):
    authorised_courses(user_id, course_id)
    return [
        {
            "resource_id": r.resource_id, "course_id": r.canvas_course_id, "title": r.title,
            "resource_type": r.resource_type.value, "week": r.week, "module": r.module_name,
            "status": r.status.value, "is_external": r.is_external, "source_provider": r.source_provider.value,
            "metadata": {k: v for k, v in r.metadata.items() if k not in {"filename"}},
        }
        for r in ResourceRepository().list(user_id, course_id)
    ]


@router.get("/{resource_id}/file")
def get_resource_file(resource_id: str, uid: str = Query(...), exp: int = Query(...), sig: str = Query(...)):
    if not verify_resource_signature(uid, resource_id, exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Link expired or invalid")
    res = ResourceRepository().get(uid, resource_id)
    if res is None or not res.local_path or not Path(res.local_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not available")
    media = res.mime_type or ("application/pdf" if res.local_path.endswith(".pdf") else "application/octet-stream")
    return FileResponse(res.local_path, media_type=media, content_disposition_type="inline",
                        filename=Path(res.local_path).name)


@router.get("/graph/stats")
def graph_stats(course_id: str, user_id: str = CurrentUser):
    authorised_courses(user_id, course_id)
    return GraphRepository().stats(user_id, course_id)
