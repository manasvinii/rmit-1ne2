from app.database.academic_repository import get_academic_repo
from app.services.graph_extraction_service import CourseGraphBuilder
from app.services.llm_service import set_llm
from tests.conftest import COURSE, STUDENT_A, STUDENT_B, auth_header


def _spec():
    get_academic_repo().upsert_courses([{"course_id": COURSE, "user_id": STUDENT_A, "course_name": "Machine Learning",
                                         "course_code": COURSE}])
    get_academic_repo().upsert_assignments([{
        "assignment_id": "a1", "course_id": COURSE, "user_id": STUDENT_A, "assignment_name": "Assignment 1",
        "description": "<p>Train a logistic regression classifier with the sigmoid function and tune the learning rate.</p>",
        "due_at": "2099-01-01T12:59:00Z",
    }])
    CourseGraphBuilder(STUDENT_A, COURSE).build()


def test_ui_is_served(client):
    assert client.get("/").status_code == 200 and "app.js" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_assignments_and_weeks_for_pickers(course, client):
    _spec()
    a = client.get("/me/assignments", headers=auth_header(STUDENT_A)).json()
    assert a[0]["name"] == "Assignment 1" and a[0]["upcoming"] and a[0]["linked_to_lectures"]
    weeks = client.get("/me/weeks", headers=auth_header(STUDENT_A)).json()
    assert [w["week"] for w in weeks] == [2, 3]


def test_quiz_from_assignment_cites_slides(course, client):
    _spec()
    r = client.post("/brainstorm/quiz", headers=auth_header(STUDENT_A),
                    json={"assignment_id": "a1", "num_questions": 3, "fast": True})
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["focus"]["name"] == "Assignment 1" and q["questions"]
    source_ids = {s["id"] for s in q["sources"]}
    for x in q["questions"]:
        assert x["source_id"] in source_ids and 0 <= x["answer_index"] < len(x["options"])
    assert any(c["assessed"] for c in q["concepts"])


class _QuizLLM:
    name = "fake"

    def complete(self, *a, **k):
        return ""

    def complete_json(self, system, user, schema, name):
        return {"questions": [
            {"question": "What does the sigmoid function output [S1]?", "source": "S1", "answer_index": 4,
             "options": ["A label", "A loss", "A gradient", "A weight", "A probability between zero and one"],
             "explanation": "It maps a score to a probability."},
            {"question": "Unsupported", "source": "S99", "answer_index": 0, "options": ["a", "b", "c", "d"],
             "explanation": "x"},
        ]}


def test_llm_quiz_is_validated_and_trimmed(course, client):
    _spec()
    set_llm(_QuizLLM())
    q = client.post("/brainstorm/quiz", headers=auth_header(STUDENT_A),
                    json={"assignment_id": "a1", "num_questions": 1}).json()
    first = q["questions"][0]
    assert q["method"] == "llm" and "[S1]" not in first["question"]
    assert len(first["options"]) == 4 and first["options"][first["answer_index"]].startswith("A probability")


def test_quiz_cannot_use_another_students_assignment(course, client):
    _spec()
    r = client.post("/brainstorm/quiz", headers=auth_header(STUDENT_B), json={"assignment_id": "a1", "fast": True})
    assert r.status_code in (403, 422)


def test_fast_query_skips_llm(course, client):
    class Boom(_QuizLLM):
        def complete(self, *a, **k):
            raise AssertionError("LLM must not be called in fast mode")
    set_llm(Boom())
    r = client.post("/query", headers=auth_header(STUDENT_A), json={"query": "What is gradient descent?", "fast": True})
    assert r.status_code == 200 and r.json()["sources"]
