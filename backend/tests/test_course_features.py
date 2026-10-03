"""Week overviews, assignment-to-lecture linking from the Canvas spec, and keeping similar courses apart."""

from app.database.academic_repository import get_academic_repo
from app.database.graph_repository import GraphRepository
from app.database.resource_repository import ResourceRepository
from app.services.answer_service import AnswerService
from app.services.course_scope import courses_mentioned, strip_course_mentions
from app.services.graph_extraction_service import CourseGraphBuilder
from app.services.query_router import Intent, route_query
from tests.conftest import COURSE, STUDENT_A, STUDENT_B

COURSES = {
    "171223": {"course_code": "COSC2793", "course_name": "Computational Machine Learning (2650)"},
    "170001": {"course_code": "COSC2673", "course_name": "Machine Learning (2650)"},
    "170002": {"course_code": "MATH2349", "course_name": "Data Wrangling (2550)"},
}


def test_week_overview_routing():
    for q in ("What was covered in Week 3?", "Summarise week 5", "Tell me about lecture 7",
              "What's new in week 6?", "What did we learn in week 2"):
        assert route_query(q).intent == Intent.WEEK_OVERVIEW, q
    assert route_query("Where did the lecturer discuss dropout in week 7?").intent != Intent.WEEK_OVERVIEW
    assert route_query("How does week 3 connect to week 7?").intent == Intent.LECTURE_CONNECTION


def test_similar_course_names_resolve_to_one_course():
    assert courses_mentioned("Computational Machine Learning week 7", COURSES) == {"171223"}
    assert courses_mentioned("what's due in COSC2673?", COURSES) == {"170001"}
    assert courses_mentioned("data wrangling deadline", COURSES) == {"170002"}
    assert courses_mentioned("what is gradient descent?", COURSES) == set()


def test_course_name_is_not_treated_as_a_concept():
    q = strip_course_mentions("In Computational Machine Learning, what is dropout?", COURSES, {"171223"})
    assert "machine" not in q.lower() and "dropout" in q


def test_week_overview_uses_only_that_week(course):
    resp = AnswerService().answer(STUDENT_A, [COURSE], "What was covered in week 3?")
    assert resp.intent == Intent.WEEK_OVERVIEW.value
    assert resp.sources and all(s.week == 3 for s in resp.sources)
    assert "Logistic Regression" in resp.reply
    assert "Gradient Descent" in resp.reply.split("Recapped from earlier weeks:")[1]


def _add_spec():
    get_academic_repo().upsert_assignments([{
        "assignment_id": "a1", "course_id": COURSE, "user_id": STUDENT_A, "assignment_name": "Assignment 1",
        "description": "<p>Train a logistic regression classifier on the data set and report how the "
                       "learning rate affects convergence.</p>",
        "due_at": "2099-01-01T12:59:00Z",
    }])
    CourseGraphBuilder(STUDENT_A, COURSE).build()


def test_assignment_lectures_grouped_by_week(course):
    _add_spec()
    resp = AnswerService().answer(STUDENT_A, [COURSE], "What lectures do I need for Assignment 1?")
    assert resp.intent == Intent.ASSIGNMENT_REVISION.value
    lines = resp.reply.splitlines()
    week3 = next(line for line in lines if line.startswith("• Week 3"))
    week2 = next(line for line in lines if line.startswith("• Week 2"))
    assert "Logistic Regression" in week3 and "Learning Rate" in week2
    assert "Train a logistic regression classifier" in resp.reply  # quote comes from the Canvas spec


def test_purge_course_removes_resources_and_graph(course):
    assert ResourceRepository().delete_course(STUDENT_A, COURSE) > 0
    GraphRepository().clear_course(STUDENT_A, COURSE)
    assert not GraphRepository().list_nodes(STUDENT_A, [COURSE], ["Lecture"])
    assert not ResourceRepository().list(STUDENT_A, COURSE)
    assert ResourceRepository().list(STUDENT_B, COURSE)  # another student's copy of the course is untouched
