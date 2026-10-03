"""Pupil API: subjects/materials from the synced store, week + material scoping, teaching sessions."""

import json

from app.database.teaching_repository import TeachingRepository
from app.services.document_service import extract_notebook_sections
from app.services.llm_service import set_llm
from tests.conftest import COURSE, STUDENT_A, STUDENT_B, auth_header

WEEK2_IDEAS = {"gradient descent", "loss function", "learning rate"}
WEEK3_ONLY = {"logistic regression", "sigmoid function"}


def _start(client, headers=None, **body):
    payload = {"subjectId": COURSE, "persona": "pip", "fast": True, **body}
    return client.post("/api/sessions", headers=headers or auth_header(STUDENT_A), json=payload)


def test_subjects_list_weeks_with_material(course, client):
    r = client.get("/api/subjects", headers=auth_header(STUDENT_A))
    assert r.status_code == 200
    (s,) = r.json()["subjects"]
    assert s["id"] == COURSE and s["weeksWithMaterial"] == [2, 3]
    assert len(s["topics"]) == s["totalWeeks"] == 12 and len(s["progress"]) == 12


def test_materials_single_week_and_combinations(course, client):
    h = auth_header(STUDENT_A)
    week3 = client.get(f"/api/subjects/{COURSE}/materials", params={"week": 3}, headers=h).json()
    assert {m["kind"] for m in week3} == {"slides", "video"} and all(m["source"]["url"] for m in week3)
    both = client.get(f"/api/subjects/{COURSE}/materials", params={"weeks": "2,3"}, headers=h).json()
    slides = next(m for m in both if m["kind"] == "slides")
    assert slides["id"] == "group-slides" and len(slides["items"]) == 2
    rng = client.get(f"/api/subjects/{COURSE}/materials", params={"week": 3, "mode": "range"}, headers=h).json()
    assert [m["id"] for m in rng] == [m["id"] for m in both]


def test_materials_need_auth_and_enrolment(course, client):
    assert client.get(f"/api/subjects/{COURSE}/materials", params={"week": 2}).status_code == 401
    r = client.get("/api/subjects/OTHER999/materials", params={"week": 2}, headers=auth_header(STUDENT_A))
    assert r.status_code == 403
    assert client.get(f"/api/subjects/{COURSE}/materials", params={"weeks": "0,99"},
                      headers=auth_header(STUDENT_A)).status_code == 422


def test_content_only_contains_selected_weeks_and_materials(course, client):
    h = auth_header(STUDENT_A)
    w2 = client.get(f"/api/subjects/{COURSE}/content", params={"week": 2}, headers=h).json()
    assert "learning rate" in w2["text"].lower() and "logistic" not in w2["text"].lower()
    week3 = client.get(f"/api/subjects/{COURSE}/materials", params={"week": 3}, headers=h).json()
    slides = next(m["id"] for m in week3 if m["kind"] == "slides")
    only_video = client.get(f"/api/subjects/{COURSE}/content", params={"week": 3, "exclude": slides}, headers=h).json()
    assert {m["id"] for m in only_video["materials"]} == {m["id"] for m in week3 if m["kind"] == "video"}
    assert only_video["text"] and "(p." not in only_video["text"]  # transcript blocks only, no slide pages


def test_student_b_private_notes_never_reach_student_a(course, client):
    text = client.get(f"/api/subjects/{COURSE}/content", params={"weeks": "2,3"}, headers=auth_header(STUDENT_A)).json()["text"]
    assert "zebrafish" not in text.lower()


def test_session_ideas_come_from_the_chosen_week_only(course, client):
    r = _start(client, week=2)
    assert r.status_code == 201, r.text
    names = {i["name"].lower() for i in r.json()["ideas"]}
    assert names and names <= WEEK2_IDEAS | {"regression"} and not names & WEEK3_ONLY
    assert r.json()["ideas"][0]["state"] == "current" and r.json()["messages"][0]["from"] == "student"


def test_unticking_everything_is_rejected(course, client):
    h = auth_header(STUDENT_A)
    ids = [m["id"] for m in client.get(f"/api/subjects/{COURSE}/materials", params={"week": 3}, headers=h).json()]
    assert _start(client, week=3, exclude=ids).status_code == 422


def test_full_session_turns_hint_and_map(course, client):
    h = auth_header(STUDENT_A)
    v = _start(client, week=2).json()
    sid, first = v["id"], v["ideas"][0]["name"]
    v = client.post(f"/api/sessions/{sid}/messages", headers=h, json={"text": "hello"}).json()
    assert v["ideas"][0]["state"] == "current"  # too short to judge
    good = ("Gradient descent is an optimisation algorithm: it iteratively updates the model parameters in the "
            "direction of the negative gradient of the loss function, and the learning rate sets the step size.")
    v = client.post(f"/api/sessions/{sid}/messages", headers=h, json={"text": good, "via": "voice"}).json()
    assert v["messages"][-2]["from"] == "me" and v["messages"][-2]["via"] == "voice"
    v = client.post(f"/api/sessions/{sid}/hint", headers=h).json()
    assert v["messages"][-1]["type"] == "hint"
    m = client.post(f"/api/sessions/{sid}/end", headers=h).json()
    assert m["total"] == len(m["nodes"]) and {n["status"] for n in m["nodes"]} <= {"E", "S", "G", "N"}
    assert any(n["status"] != "N" for n in m["nodes"]) and first in {n["title"] for n in m["nodes"]}
    assert len(m["semester"]) == 12 and m["semester"][1] == "T"
    assert client.get(f"/api/sessions/{sid}/map", headers=h).json()["nodes"] == m["nodes"]
    progress = client.get("/api/subjects", headers=h).json()["subjects"][0]["progress"]
    assert progress[1] in "ESG"


def test_session_belongs_to_its_student(course, client):
    sid = _start(client, week=2).json()["id"]
    b = auth_header(STUDENT_B)
    assert client.get(f"/api/sessions/{sid}", headers=b).status_code == 404
    assert client.post(f"/api/sessions/{sid}/messages", headers=b, json={"text": "hi there"}).status_code == 404
    assert client.post(f"/api/sessions/{sid}/end", headers=b).status_code == 404


def test_reteach_keeps_scope_and_focuses_on_weak_spots(course, client):
    h = auth_header(STUDENT_A)
    week3 = client.get(f"/api/subjects/{COURSE}/materials", params={"week": 3}, headers=h).json()
    video = next(m["id"] for m in week3 if m["kind"] == "video")
    v = _start(client, week=3, exclude=[video]).json()
    sid = v["id"]
    client.post(f"/api/sessions/{sid}/messages", headers=h, json={"text": "I am not sure, something about lines?"})
    weak = {n["title"] for n in client.post(f"/api/sessions/{sid}/end", headers=h).json()["nodes"] if n["status"] in "GS"}

    r = client.post(f"/api/sessions/{sid}/reteach", headers=h, json={"fast": True})
    assert r.status_code == 201, r.text
    again = r.json()
    assert again["id"] != sid and again["weeks"] == [3] and again["persona"] == "pip"
    if weak:
        assert {i["name"] for i in again["ideas"]} <= weak
    from app.database.teaching_repository import TeachingRepository
    assert video not in TeachingRepository().get(STUDENT_A, again["id"])["resource_ids"]

    milo = client.post(f"/api/sessions/{sid}/reteach", headers=h, json={"persona": "milo", "fast": True}).json()
    assert milo["persona"] == "milo" and milo["weeks"] == [3]
    assert client.post(f"/api/sessions/{sid}/reteach", headers=auth_header(STUDENT_B), json={}).status_code == 404


def test_turn_evidence_stays_inside_the_selected_scope(course, client):
    h = auth_header(STUDENT_A)
    week3 = client.get(f"/api/subjects/{COURSE}/materials", params={"week": 3}, headers=h).json()
    video = next(m["id"] for m in week3 if m["kind"] == "video")
    slides = next(m["id"] for m in week3 if m["kind"] == "slides")
    sid = _start(client, week=3, exclude=[slides]).json()["id"]
    client.post(f"/api/sessions/{sid}/messages", headers=h,
                json={"text": "Logistic regression uses the sigmoid function to turn a score into a probability."})
    used = {e["resource_id"] for t in TeachingRepository().turns(STUDENT_A, sid) for e in t["evidence"]}
    assert used == {video}


class _PersonaLLM:
    name = "fake"

    def __init__(self):
        self.calls = []

    def complete(self, *a, **k):
        return ""

    def complete_json(self, system, user, schema, name):
        self.calls.append(user)
        return {"reply": "Ohh, so it walks downhill [S1]! What's a learning rate then?", "verdict": "explained",
                "feedback": "You covered the negative gradient [S1].", "flag": "S1", "notebook": "GD walks downhill",
                "source": "S9"}


def test_llm_turn_is_validated(course, client):
    llm = _PersonaLLM()
    set_llm(llm)
    h = auth_header(STUDENT_A)
    v = _start(client, week=2, fast=False).json()
    v = client.post(f"/api/sessions/{v['id']}/messages", headers=h,
                    json={"text": "Gradient descent steps against the gradient of the loss."}).json()
    assert v["method"] == "llm" and "[S1]" not in v["messages"][-1]["text"]
    assert not any(m.get("type") == "flag" for m in v["messages"])  # "S1" is not a flag
    assert v["ideas"][0]["state"] == "E" and v["ideas"][1]["state"] == "current"
    assert "zebrafish" not in llm.calls[0].lower() and "EXCERPTS" in llm.calls[0]


def test_greetings_skip_the_llm_and_keep_the_idea(course, client):
    llm = _PersonaLLM()
    set_llm(llm)
    h = auth_header(STUDENT_A)
    v = _start(client, week=2, fast=False).json()
    first = v["ideas"][0]["name"]
    for hello in ("hello", "Hi Pip!", "hey, can you hear me?", "ok thanks"):
        v = client.post(f"/api/sessions/{v['id']}/messages", headers=h, json={"text": hello}).json()
        assert v["method"] == "small_talk" and first in v["messages"][-1]["text"]
    assert not llm.calls
    assert v["ideas"][0]["state"] == "current" and not any(m.get("type") == "flag" for m in v["messages"])


class _RoleSwapLLM(_PersonaLLM):
    def complete_json(self, system, user, schema, name):
        self.calls.append(system)
        return {"reply": "Hello Pip! I'm happy to help explain it. Imagine a hill...", "verdict": "shaky",
                "feedback": "", "flag": "important detail missing", "notebook": "", "source": "S1"}


def test_role_swapped_llm_reply_is_discarded(course, client):
    llm = _RoleSwapLLM()
    set_llm(llm)
    h = auth_header(STUDENT_A)
    v = _start(client, week=2, fast=False).json()
    v = client.post(f"/api/sessions/{v['id']}/messages", headers=h,
                    json={"text": "Gradient descent steps against the gradient of the loss."}).json()
    assert v["method"] == "rules" and "Hello Pip" not in v["messages"][-1]["text"]
    assert "the STUDENT" in llm.calls[0] and "Never call the tutor Pip" in llm.calls[0]


def test_notebook_sections(tmp_path):
    nb = tmp_path / "Week_02_Lab.ipynb"
    nb.write_text(json.dumps({"cells": [
        {"cell_type": "markdown", "source": ["# Week 2 Lab\n", "Intro text"]},
        {"cell_type": "markdown", "source": "## Gradient descent\nWe minimise the loss step by step."},
        {"cell_type": "code", "source": "w = w - lr * grad\n", "outputs": [{"text": "ignored"}]},
    ]}))
    secs = extract_notebook_sections(nb)
    assert [s.heading for s in secs] == ["Week 2 Lab", "Gradient descent"]
    assert secs[1].page == 2 and "w = w - lr * grad" in secs[1].text and "ignored" not in secs[1].text
