"""Pupil API (the Angular app in frontend/): subjects, weeks and materials from the student's synced
Canvas store, and teaching sessions with an AI student grounded in the selected material.

Every route needs the backend-issued bearer token; the student is never taken from the request body.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from app.core.auth import CurrentUser
from app.core.config import get_settings
from app.core.security import create_access_token
from app.database.academic_repository import get_academic_repo
from app.models.schemas import TeachReteachRequest, TeachStartRequest, TeachTurnRequest
from app.services.study_catalog import ScopeError, StudyCatalog, parse_weeks
from app.services.teaching_service import SessionNotFound, TeachingService

router = APIRouter(prefix="/api", tags=["pupil"])


def _guard(fn):
    try:
        return fn()
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    except SessionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    except (ScopeError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))


def _weeks(week: Optional[int], mode: str, weeks: Optional[str]) -> list[int]:
    return _guard(lambda: parse_weeks(week, mode, weeks))


def _ids(raw: str) -> set[str]:
    return {s for s in (raw or "").split(",") if s}


@router.get("/health")
def health():
    return {"ok": True}


@router.post("/demo-login")
def demo_login():
    """"Continue with Canvas" in the demo build: signs in as the student named by DEMO_USER_EMAIL.
    Disabled unless that variable is set, and always disabled in production."""
    settings = get_settings()
    email = os.getenv("DEMO_USER_EMAIL", "").strip().lower()
    if not email or settings.env == "production":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demo sign-in is not enabled")
    user = get_academic_repo().get_user_by_email(email)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demo student not found")
    uid = str(user["user_id"])
    return {"access_token": create_access_token(uid), "token_type": "bearer", "user_id": uid,
            "name": user.get("full_name"), "expires_in": settings.jwt_ttl_minutes * 60}


@router.get("/me")
def me(user_id: str = CurrentUser):
    user = get_academic_repo().get_user(user_id) or {}
    return {"id": user_id, "name": user.get("full_name"), "email": user.get("email"), "via": "canvas"}


@router.get("/subjects")
def subjects(user_id: str = CurrentUser):
    """Course names, topic per week and the week strip (E/S/G from past sessions, N released, U upcoming)."""
    teaching = TeachingService()
    course_ids = {s["course_id"] for s in teaching.repo.list(user_id)}
    return StudyCatalog().subjects(user_id, {cid: teaching.progress(user_id, cid) for cid in course_ids})


@router.get("/subjects/{course_id}/weeks")
def weeks(course_id: str, user_id: str = CurrentUser):
    catalog = StudyCatalog()
    return _guard(lambda: (catalog.authorise(user_id, course_id), catalog.weeks_overview(user_id, course_id))[1])


@router.get("/subjects/{course_id}/materials")
def materials(course_id: str, week: Optional[int] = Query(None, ge=1, le=20),
              mode: str = Query("single", pattern="^(single|range)$"),
              weeks: Optional[str] = Query(None, description="Any combination, e.g. 2,5,9 (overrides week/mode)"),
              user_id: str = CurrentUser):
    """Materials the AI student can learn from: one row per file for a single week, one row per kind
    (with `items`) for several weeks."""
    ws = _weeks(week, mode, weeks)
    catalog = StudyCatalog()
    return _guard(lambda: (catalog.authorise(user_id, course_id), catalog.materials(user_id, course_id, ws))[1])


@router.get("/subjects/{course_id}/content")
def content(course_id: str, week: Optional[int] = Query(None, ge=1, le=20),
            mode: str = Query("single", pattern="^(single|range)$"), weeks: Optional[str] = None,
            exclude: str = "", include: str = "", user_id: str = CurrentUser):
    """Plain text of exactly the selected materials (what the AI student is allowed to know)."""
    ws = _weeks(week, mode, weeks)
    catalog = StudyCatalog()
    return _guard(lambda: catalog.content(catalog.resolve_scope(user_id, course_id, ws, _ids(exclude), _ids(include))))


@router.get("/subjects/{course_id}/download")
def download(course_id: str, week: Optional[int] = Query(None, ge=1, le=20),
             mode: str = Query("single", pattern="^(single|range)$"), weeks: Optional[str] = None,
             exclude: str = "", include: str = "", user_id: str = CurrentUser):
    """Zip of the selected materials' local copies."""
    ws = _weeks(week, mode, weeks)
    catalog = StudyCatalog()
    name, data = _guard(lambda: catalog.zip_bytes(catalog.resolve_scope(user_id, course_id, ws, _ids(exclude), _ids(include))))
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------------- teaching sessions
@router.post("/sessions", status_code=201)
def start_session(body: TeachStartRequest, user_id: str = CurrentUser):
    ws = _weeks(body.week, body.mode, ",".join(map(str, body.weeks)) if body.weeks else None)
    return _guard(lambda: TeachingService().start(
        user_id, str(body.subject_id), ws, body.persona, body.exclude, body.include,
        length=body.length, input_mode=body.input, fast=body.fast))


@router.get("/sessions")
def list_sessions(subject_id: Optional[str] = Query(None, alias="subjectId"), user_id: str = CurrentUser):
    svc = TeachingService()
    return [{"id": s["session_id"], "subjectId": s["course_id"], "persona": s["persona"], "weeks": s["weeks"],
             "startedAt": s["started_at"], "endedAt": s["ended_at"],
             "landed": (s["summary"] or {}).get("landed"), "total": (s["summary"] or {}).get("total")}
            for s in svc.repo.list(user_id, subject_id)]


@router.get("/sessions/{session_id}")
def get_session(session_id: str, user_id: str = CurrentUser):
    return _guard(lambda: TeachingService().view(user_id, session_id))


@router.post("/sessions/{session_id}/messages")
def send_message(session_id: str, body: TeachTurnRequest, user_id: str = CurrentUser):
    return _guard(lambda: TeachingService().turn(user_id, session_id, body.text, body.via))


@router.post("/sessions/{session_id}/hint")
def hint(session_id: str, user_id: str = CurrentUser):
    return _guard(lambda: TeachingService().hint(user_id, session_id))


@router.post("/sessions/{session_id}/end")
def end_session(session_id: str, user_id: str = CurrentUser):
    return _guard(lambda: TeachingService().end(user_id, session_id))


@router.post("/sessions/{session_id}/reteach", status_code=201)
def reteach(session_id: str, body: TeachReteachRequest, user_id: str = CurrentUser):
    """Start again on the same weeks and ticked material, focused on the shaky ideas and gaps."""
    return _guard(lambda: TeachingService().reteach(user_id, session_id, body.persona, fast=body.fast))


@router.get("/sessions/{session_id}/map")
def session_map(session_id: str, user_id: str = CurrentUser):
    return _guard(lambda: TeachingService().map(user_id, session_id))


@router.get("/gaps")
def gaps(user_id: str = CurrentUser):
    """Concepts the student couldn't explain (or was shaky on) in recent sessions, for Home."""
    return TeachingService().gaps(user_id)
