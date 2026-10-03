"""Request authentication + course authorisation dependencies."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from app.core.security import decode_access_token
from app.database.academic_repository import get_academic_repo
from app.database.resource_repository import ResourceRepository


def current_user_id(authorization: str = Header(default="")) -> str:
    """Identity comes only from the backend-issued bearer token — never from the request body."""
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token",
                            headers={"WWW-Authenticate": "Bearer"})
    user_id = decode_access_token(authorization.split(" ", 1)[1].strip())
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session",
                            headers={"WWW-Authenticate": "Bearer"})
    return user_id


def allowed_course_ids(user_id: str) -> list[str]:
    """Courses the student may query: Canvas enrolments plus courses they ingested material for."""
    ids: set[str] = set()
    try:
        ids |= {str(c["course_id"]) for c in get_academic_repo().list_courses(user_id)}
    except Exception:
        pass  # academic store offline must not expose anything; it only narrows access
    ids |= set(ResourceRepository().course_ids(user_id))
    return sorted(ids)


def authorised_courses(user_id: str, course_id: Optional[str]) -> list[str]:
    allowed = allowed_course_ids(user_id)
    if course_id is None:
        return allowed
    if str(course_id) not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not enrolled in that course")
    return [str(course_id)]


CurrentUser = Depends(current_user_id)
