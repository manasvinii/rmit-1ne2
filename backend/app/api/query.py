"""POST /query — the chatbot entry point (route -> retrieve -> fuse -> answer)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from app.api.resources import signed_resource_url
from app.core.auth import CurrentUser, authorised_courses
from app.models.schemas import QueryRequest, QueryResponse
from app.services.answer_service import AnswerService
from app.services.query_router import route_query

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, user_id: str = CurrentUser) -> QueryResponse:
    course_id: Optional[str] = str(body.course_id) if body.course_id is not None else None
    course_ids = authorised_courses(user_id, course_id)
    service = AnswerService(
        url_builder=lambda resource_id, page, t: signed_resource_url(user_id, resource_id, page, t)
    )
    return service.answer(user_id, course_ids, body.query, course_id=course_id, routed=route_query(body.query),
                          use_llm=not body.fast)
