"""Mandatory cross-student isolation: A and B share a course id, but neither may see the other's data."""

import pytest
from urllib.parse import parse_qs, urlparse

from app.core.security import sign_resource_url
from app.database.graph_repository import GraphRepository
from app.database.resource_repository import ResourceRepository
from app.database.vector_repository import ChunkFilter, VectorRepository
from app.models.resource_models import ContentChunk, ContentType
from app.services.embedding_service import HashEmbedder
from app.services.retrieval_service import RetrievalService
from app.services.query_router import route_query
from tests.conftest import COURSE, STUDENT_A, STUDENT_B, auth_header

SECRET = "zebrafish optimisation"


def _b_chunk_ids():
    return {c.chunk_id for c in VectorRepository().list_chunks(ChunkFilter(STUDENT_B, [COURSE]))}


def test_chunk_filter_requires_user():
    with pytest.raises(ValueError):
        ChunkFilter("", [COURSE]).sql()


def test_vector_and_keyword_search_never_cross_users(course):
    repo = VectorRepository()
    qvec = HashEmbedder().embed([SECRET])[0]
    flt = ChunkFilter(STUDENT_A, [COURSE])
    a_hits = repo.vector_search(flt, qvec, k=50) + repo.keyword_search(flt, ["zebrafish", "optimisation"], k=50)
    assert a_hits, "A should still get their own chunks"
    assert all(h.chunk.user_id == STUDENT_A for h in a_hits)
    assert not ({h.chunk.chunk_id for h in a_hits} & _b_chunk_ids())
    b_hits = repo.vector_search(ChunkFilter(STUDENT_B, [COURSE]), qvec, k=5)
    assert b_hits and all(h.chunk.user_id == STUDENT_B for h in b_hits)


def test_graph_reads_are_scoped_to_user(course):
    g = GraphRepository()
    a_nodes = g.list_nodes(STUDENT_A, [COURSE])
    b_nodes = g.list_nodes(STUDENT_B, [COURSE])
    assert a_nodes and b_nodes
    assert not ({n.node_id for n in a_nodes} & {n.node_id for n in b_nodes})
    assert not any("zebrafish" in n.label.lower() for n in a_nodes)
    b_ids = [n.node_id for n in b_nodes]
    assert g.get_nodes(STUDENT_A, b_ids) == {}
    assert g.edges(STUDENT_A, [COURSE], b_ids, direction="both") == []
    assert g.traverse(STUDENT_A, [COURSE], b_ids, ["REQUIRES", "INTRODUCED_IN"]) == {}


def test_hybrid_retrieval_isolated(course):
    res = RetrievalService().retrieve(STUDENT_A, [COURSE], "What is zebrafish optimisation?", route_query("What is zebrafish optimisation?"))
    assert all(e.chunk.user_id == STUDENT_A for e in res.evidence)


def test_cannot_write_chunks_into_another_users_resource(course):
    b_res = ResourceRepository().list(STUDENT_B, COURSE)[0]
    chunk = ContentChunk(chunk_id="evil", user_id=STUDENT_A, course_id=COURSE, resource_id=b_res.resource_id,
                         lecture_id="x", content_type=ContentType.SLIDE, text="injected", resource_title="x")
    with pytest.raises(Exception):
        VectorRepository().replace_resource_chunks(STUDENT_A, b_res.resource_id, [chunk])
    assert "evil" not in _b_chunk_ids()


def test_query_api_does_not_leak_and_ignores_body_user_id(course, client):
    r = client.post("/query", json={"query": "Explain zebrafish optimisation", "user_id": STUDENT_B},
                    headers=auth_header(STUDENT_A))
    assert r.status_code == 200
    body = r.json()
    assert "zebrafish" not in body["reply"].lower()
    a_resources = {x.resource_id for x in ResourceRepository().list(STUDENT_A, COURSE)}
    for s in body["sources"]:
        assert "zebrafish" not in (s.get("snippet") or "").lower()
        if s.get("url"):
            rid = urlparse(s["url"]).path.split("/")[2]
            assert rid in a_resources


def test_resource_file_requires_matching_signature(course, client):
    b_res = ResourceRepository().list(STUDENT_B, COURSE)[0]
    exp, sig = sign_resource_url(STUDENT_A, b_res.resource_id)
    # A's valid signature cannot open B's resource (signature is bound to A, resource lookup to uid)
    r = client.get(f"/resources/{b_res.resource_id}/file", params={"uid": STUDENT_A, "exp": exp, "sig": sig})
    assert r.status_code == 404
    r = client.get(f"/resources/{b_res.resource_id}/file", params={"uid": STUDENT_B, "exp": exp, "sig": sig})
    assert r.status_code == 403
    exp_b, sig_b = sign_resource_url(STUDENT_B, b_res.resource_id)
    ok = client.get(f"/resources/{b_res.resource_id}/file", params={"uid": STUDENT_B, "exp": exp_b, "sig": sig_b})
    assert ok.status_code == 200 and ok.content.startswith(b"%PDF")


def test_course_authorisation(course, client):
    r = client.post("/query", json={"query": "What is gradient descent?", "course_id": "NOT_MY_COURSE"},
                    headers=auth_header(STUDENT_A))
    assert r.status_code == 403
    r = client.get("/resources", headers=auth_header(STUDENT_A))
    assert r.status_code == 200
    assert {x["resource_id"] for x in r.json()} == {x.resource_id for x in ResourceRepository().list(STUDENT_A)}


def test_signed_url_in_sources_opens_own_file(course, client):
    r = client.post("/query", json={"query": "What is the sigmoid function?"}, headers=auth_header(STUDENT_A))
    url = next(s["url"] for s in r.json()["sources"] if s.get("url") and s["type"] in ("slides", "pdf"))
    parsed = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert q["uid"] == STUDENT_A
    assert client.get(parsed.path, params=q).status_code == 200
