from datetime import datetime, timedelta, timezone

from app.database.academic_repository import get_academic_repo
from app.services.query_router import route_query
from app.services.structured_service import answer_structured
from tests.conftest import STUDENT_A


def _iso(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_numbered_deadline_prefers_the_upcoming_one_over_old_namesakes():
    repo = get_academic_repo()
    repo.upsert_courses([
        {"course_id": "old", "course_name": "Old Course (2550)", "user_id": STUDENT_A},
        {"course_id": "now", "course_name": "Computational Machine Learning (2650)", "user_id": STUDENT_A},
    ])
    repo.upsert_assignments(
        [{"assignment_id": f"o{i}", "course_id": "old", "user_id": STUDENT_A, "assignment_name": f"Assignment 2 part {i}",
          "due_at": _iso(-300 - i)} for i in range(12)]
        + [{"assignment_id": "n2", "course_id": "now", "user_id": STUDENT_A, "assignment_name": "Assessment 2",
            "due_at": _iso(1)}]
    )
    q = "When is assessment 2 due?"
    r = answer_structured(STUDENT_A, None, q, route_query(q))
    assert r.reply.startswith("• Assessment 2 (Computational Machine Learning")
    assert len(r.sources) == 1 and "12 past assignments" in r.reply


def test_numbered_deadline_falls_back_to_most_recent_past():
    repo = get_academic_repo()
    repo.upsert_courses([{"course_id": "old", "course_name": "Old Course", "user_id": STUDENT_A}])
    repo.upsert_assignments([
        {"assignment_id": "a", "course_id": "old", "user_id": STUDENT_A, "assignment_name": "Assignment 2", "due_at": _iso(-400)},
        {"assignment_id": "b", "course_id": "old", "user_id": STUDENT_A, "assignment_name": "Assignment 2 resubmit", "due_at": _iso(-10)},
    ])
    q = "When is assignment 2 due?"
    r = answer_structured(STUDENT_A, None, q, route_query(q))
    assert r.reply.startswith("• Assignment 2 resubmit") and "past assignment" not in r.reply
