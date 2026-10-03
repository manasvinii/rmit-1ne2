"""Existing prototype endpoints (courses, find classmate) — same response shapes, now
authenticated and restricted to the caller's own data."""

from __future__ import annotations

import logging
from typing import List, Union

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.auth import CurrentUser
from app.database.academic_repository import get_academic_repo

log = logging.getLogger(__name__)
router = APIRouter(tags=["academic"])


def _course_view(course: dict) -> dict:
    return {
        "id": course.get("course_id"),
        "name": course.get("course_name"),
        "course_code": course.get("course_code"),
        "created_at": course.get("created_at"),
        "start_at": course.get("start_at"),
        "end_at": course.get("end_at"),
        "apply_assignment_group_weights": course.get("apply_assignment_group_weights"),
    }


@router.get("/me/courses")
def my_courses(user_id: str = CurrentUser):
    return [_course_view(c) for c in get_academic_repo().list_courses(user_id)]


@router.get("/users/{path_user_id}/courses")
def get_user_courses(path_user_id: str, user_id: str = CurrentUser):
    if str(path_user_id) != str(user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only view your own courses")
    courses = get_academic_repo().list_courses(user_id)
    if not courses:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No courses found. Sync Canvas first.")
    return [_course_view(c) for c in courses]


@router.get("/users/{path_user_id}/courses/find_classmate")
def get_user_courses_alias(path_user_id: str, user_id: str = CurrentUser):
    """Path used by the chat-view component."""
    return get_user_courses(path_user_id, user_id)


class ClassmateRequest(BaseModel):
    is_theory: bool
    course_id: Union[int, str]
    day_of_course: str
    time_of_day: str
    room_of_course: str
    user_id: Union[int, str, None] = None  # ignored: identity comes from the session


@router.post("/find_classmate")
def find_classmate(requests_: List[ClassmateRequest], user_id: str = CurrentUser):
    repo = get_academic_repo()
    for req in requests_:
        course = repo.get_course(user_id, str(req.course_id))
        if not course:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Course does not exist; check the course_id")
        if not repo.timetable_entry_exists(user_id, str(req.course_id)):
            repo.insert_timetable({
                "user_id": user_id, "course_id": str(req.course_id), "day_of_course": req.day_of_course,
                "time_of_day": req.time_of_day, "room_of_course": req.room_of_course,
                "course_name": course.get("course_name"), "is_theory": req.is_theory,
            })

    slots = repo.list_timetable(user_id)
    if not slots:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No timetable saved for this user")
    matches = []
    for slot in slots:
        for c in repo.find_same_slot(user_id, slot):
            matches.append({
                "user_id": c["user_id"], "course_id": c["course_id"], "day": c["day_of_course"],
                "time": c["time_of_day"], "room": c["room_of_course"], "course_name": c["course_name"],
                "is_theory": c["is_theory"],
            })
    msg = "Classmates found successfully" if matches else "No classmates found for all courses"
    return {"message": msg, "count": len(matches), "data": matches}
