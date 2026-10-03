"""Canvas sync (courses + assignments) and module discovery (metadata only)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.auth import CurrentUser, authorised_courses
from app.database.resource_repository import ResourceRepository
from app.services import canvas_service
from app.services.canvas_service import CanvasAuthError, CanvasError

router = APIRouter(prefix="/canvas", tags=["canvas"])


def _canvas_errors(fn):
    try:
        return fn()
    except CanvasAuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            f"{e}. Generate a new token in Canvas → Account → Settings and update it.")
    except CanvasError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))


@router.post("/sync")
def sync(user_id: str = CurrentUser):
    """Fetch the student's courses and assignments from Canvas into the academic tables."""
    return _canvas_errors(lambda: canvas_service.sync_courses_and_assignments(user_id))


@router.post("/courses/{course_id}/discover")
def discover(course_id: str, user_id: str = CurrentUser):
    """Record module resources (Files, Pages, ExternalUrl, ExternalTool/LTI) — metadata only.

    Files are not downloaded and LTI tools are only catalogued as external resources.
    """
    authorised_courses(user_id, course_id)

    def run():
        client = canvas_service.client_for_user(user_id)
        found = canvas_service.discover_course_resources(client, course_id, user_id)
        repo = ResourceRepository()
        for r in found:
            repo.upsert(r)
        return {
            "discovered": len(found),
            "by_type": {t: sum(1 for r in found if r.resource_type.value == t) for t in {r.resource_type.value for r in found}},
            "external": sum(1 for r in found if r.is_external),
        }

    return _canvas_errors(run)
