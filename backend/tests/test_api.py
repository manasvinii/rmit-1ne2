from app.core.security import is_encrypted
from app.database.academic_repository import SqlAcademicRepository
from tests.conftest import COURSE, PASSWORD, STUDENT_A, STUDENT_B, auth_header


def _signup(client, email="s3000001@student.rmit.edu.au", token=None):
    return client.post("/signup", json={"name": "Test Student", "email": email, "password": PASSWORD,
                                        "api_token": token})


def test_signup_hashes_password_and_encrypts_canvas_token(client):
    r = _signup(client, token="7036~AbCdEfGhIjKlMnOpQrStUvWxYz")
    assert r.status_code == 201 and r.json()["data"]["user_id"] == "3000001"
    row = SqlAcademicRepository().get_user("3000001")
    assert row["password"].startswith("$2") and PASSWORD not in row["password"]
    assert is_encrypted(row["api_token"]) and "AbCdEf" not in row["api_token"]
    assert _signup(client).status_code == 400  # duplicate


def test_signup_accepts_legacy_query_params(client):
    r = client.post("/signup", params={"name": "Legacy", "email": "s3000002@student.rmit.edu.au", "password": PASSWORD})
    assert r.status_code == 201


def test_login_returns_session_and_never_the_canvas_token(client):
    _signup(client, token="7036~AbCdEfGhIjKlMnOpQrStUvWxYz")
    r = client.post("/login", json={"email": "s3000001@student.rmit.edu.au", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "3000001" and body["token_type"] == "bearer"
    assert "AbCdEf" not in r.text and "api_token" not in body
    me = client.get("/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["has_canvas_token"] is True
    assert "AbCdEf" not in me.text


def test_login_failures_are_indistinguishable(client):
    _signup(client)
    wrong = client.post("/login", json={"email": "s3000001@student.rmit.edu.au", "password": "nope"})
    unknown = client.post("/login", json={"email": "s9999999@student.rmit.edu.au", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_legacy_plaintext_password_is_migrated_on_login(client):
    SqlAcademicRepository().create_user({"user_id": "3000003", "full_name": "Old", "email": "old@x.com",
                                         "api_token": None, "password": "plain-old-pw"})
    assert client.post("/login", json={"email": "old@x.com", "password": "plain-old-pw"}).status_code == 200
    assert SqlAcademicRepository().get_user("3000003")["password"].startswith("$2")


def test_protected_endpoints_require_token(client):
    assert client.post("/query", json={"query": "hi"}).status_code == 401
    assert client.get("/me/courses").status_code == 401
    assert client.post("/query", json={"query": "hi"}, headers={"Authorization": "Bearer junk"}).status_code == 401


def test_query_contract(course, client):
    r = client.post("/query", json={"query": "What is gradient descent?", "course_id": COURSE},
                    headers=auth_header(STUDENT_A))
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"reply", "sources", "route", "confidence"}
    assert body["route"] in {"STRUCTURED_CANVAS", "VECTOR_RAG", "GRAPH", "GRAPH_VECTOR"}
    assert 0 <= body["confidence"] <= 1 and body["sources"]
    s = body["sources"][0]
    assert s["course_id"] == COURSE and s["week"] in (2, 3) and (s["page"] or s["timestamp"])


def test_query_video_sources_have_timestamps(course, client):
    r = client.post("/query", json={"query": "Where did the lecturer talk about the learning rate overshooting?"},
                    headers=auth_header(STUDENT_A))
    videos = [s for s in r.json()["sources"] if s["type"] == "video"]
    assert videos and all(v["start_time"] is not None and v["timestamp"] for v in videos)


def test_query_validation(client):
    h = auth_header(STUDENT_A)
    assert client.post("/query", json={"query": "   "}, headers=h).status_code == 422
    assert client.post("/query", json={}, headers=h).status_code == 422
    assert client.post("/query", json={"query": "x" * 2001}, headers=h).status_code == 422


def test_users_can_only_list_their_own_courses(course, client):
    assert client.get(f"/users/{STUDENT_B}/courses", headers=auth_header(STUDENT_A)).status_code == 403


def test_structured_route_without_synced_assignments_is_honest(course, client):
    r = client.post("/query", json={"query": "When is Assignment 2 due?"}, headers=auth_header(STUDENT_A))
    body = r.json()
    assert body["route"] == "STRUCTURED_CANVAS"
    assert body["confidence"] < 0.5


def test_health_and_cors(client):
    assert client.get("/health").status_code == 200
    r = client.options("/query", headers={"Origin": "http://localhost:4200", "Access-Control-Request-Method": "POST",
                                          "Access-Control-Request-Headers": "authorization,content-type"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:4200"
    evil = client.options("/query", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert evil.headers.get("access-control-allow-origin") is None
