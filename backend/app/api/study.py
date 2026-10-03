"""Endpoints behind the study UI: assignment and week pickers, and Brainstorm quizzes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status

from app.api.resources import signed_resource_url
from app.core.auth import CurrentUser, authorised_courses
from app.database.academic_repository import get_academic_repo
from app.database.graph_repository import GraphRepository
from app.models.graph_models import NodeType
from app.models.schemas import QuizRequest
from app.services.quiz_service import QuizError, QuizService

router = APIRouter(tags=["study"])


@router.get("/me/assignments")
def my_assignments(course_id: Optional[str] = None, user_id: str = CurrentUser):
    course_ids = set(authorised_courses(user_id, course_id))
    repo = get_academic_repo()
    names = {str(c["course_id"]): c.get("course_name") for c in repo.list_courses(user_id)}
    with_graph = {str(n.course_id) for n in GraphRepository().list_nodes(user_id, sorted(course_ids), [NodeType.ASSIGNMENT.value])}
    now = datetime.now(timezone.utc).isoformat()
    rows = [a for a in repo.list_assignments(user_id) if str(a.get("course_id")) in course_ids]
    out = [{
        "id": str(a.get("assignment_id")), "name": a.get("assignment_name"), "course_id": str(a.get("course_id")),
        "course_name": names.get(str(a.get("course_id"))), "due_at": a.get("due_at"),
        "points": a.get("points_possible"), "html_url": a.get("html_url"),
        "upcoming": bool(a.get("due_at") and a["due_at"] >= now),
        "has_spec": bool((a.get("description") or "").strip()),
        "linked_to_lectures": str(a.get("course_id")) in with_graph,
    } for a in rows]
    upcoming = sorted((a for a in out if a["upcoming"]), key=lambda a: a["due_at"])
    past = sorted((a for a in out if not a["upcoming"]), key=lambda a: a["due_at"] or "", reverse=True)
    return upcoming + past


@router.get("/me/weeks")
def my_weeks(course_id: Optional[str] = None, user_id: str = CurrentUser):
    course_ids = authorised_courses(user_id, course_id)
    lectures = GraphRepository().list_nodes(user_id, course_ids, [NodeType.LECTURE.value])
    return sorted(({"course_id": str(n.course_id), "week": n.properties.get("week"), "label": n.label,
                    "title": n.properties.get("title")} for n in lectures),
                  key=lambda w: (w["course_id"], w["week"] or 0))


@router.post("/brainstorm/quiz")
def brainstorm_quiz(body: QuizRequest, user_id: str = CurrentUser):
    course_ids = authorised_courses(user_id, str(body.course_id) if body.course_id is not None else None)
    service = QuizService(url_builder=lambda rid, page, t: signed_resource_url(user_id, rid, page, t))
    try:
        return service.generate(user_id, course_ids, assignment_id=body.assignment_id, week=body.week,
                                num_questions=body.num_questions, use_llm=not body.fast)
    except QuizError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
