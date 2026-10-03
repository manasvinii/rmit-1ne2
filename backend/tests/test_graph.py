from app.database.graph_repository import GraphRepository
from app.database.vector_repository import ChunkFilter, VectorRepository
from app.models.graph_models import LECTURE_RELATIONS, SEMANTIC_RELATIONS, Relation
from app.models.resource_models import ContentChunk, ContentType
from app.services.entity_resolution import normalize
from app.services.graph_extraction_service import CourseGraphBuilder, _quote_supported
from tests.conftest import COURSE, STUDENT_A


class FakeLLM:
    name = "fake-llm"

    def __init__(self, payload):
        self.payload = payload

    def complete(self, system, user, temperature=0.1):
        return ""

    def complete_json(self, system, user, schema, schema_name):
        return self.payload


def _chunk(text: str) -> ContentChunk:
    return ContentChunk(chunk_id="c1", user_id=STUDENT_A, course_id=COURSE, resource_id="r1", lecture_id="l1",
                        content_type=ContentType.SLIDE, text=text, heading="Logistic Regression", week=3,
                        resource_title="Lecture 3", page_number=3)


def _concept(g: GraphRepository, label: str):
    hits = g.find_by_alias(STUDENT_A, [COURSE], [normalize(label)])
    ids = hits.get(normalize(label))
    assert ids, f"concept {label!r} not in graph"
    return g.get_nodes(STUDENT_A, ids)[ids[0]]


def test_llm_output_is_validated_against_the_chunk():
    text = "Logistic regression uses gradient descent to minimise the log loss over the training examples."
    payload = {
        "concepts": [
            {"name": "Logistic Regression", "type": "Concept", "aliases": ["Logit Model"]},  # alias not in text
            {"name": "x"},  # too short
            {"name": "Support Vector Machine"},  # not in the excerpt
        ],
        "relations": [
            {"source": "Logistic Regression", "relation": "USES", "target": "Gradient Descent",
             "evidence_quote": "Logistic regression uses gradient descent", "confidence": 0.9},
            {"source": "Logistic Regression", "relation": "USES", "target": "Transformers",
             "evidence_quote": "logistic regression is the basis of transformers", "confidence": 0.9},  # not in text
            {"source": "A thing", "relation": "LOVES", "target": "Other thing",
             "evidence_quote": "Logistic regression uses gradient descent", "confidence": 0.9},  # bad relation
            {"source": "Logistic Regression", "relation": "USES", "target": "Gradient Descent",
             "evidence_quote": "Logistic regression uses gradient descent", "confidence": 7},  # bad confidence
            {"source": "Sigmoid Function", "relation": "CONTRASTS_WITH", "target": "Logistic Regression",
             "evidence_quote": "minimise the log loss over the training examples", "confidence": 0.9},  # quote names neither
        ],
    }
    b = CourseGraphBuilder(STUDENT_A, COURSE, llm=FakeLLM(payload))
    ext = b._llm_extract(_chunk(text))
    assert [c.name for c in ext.concepts] == ["Logistic Regression"]
    assert ext.concepts[0].aliases == []
    assert len(ext.relations) == 1 and ext.relations[0].target == "Gradient Descent"
    assert b.stats["llm_unsupported_quotes"] == 1
    assert b.stats["llm_rejected_relations"] == 2
    assert b.stats["llm_quote_missing_endpoint"] == 1


def test_quote_support_tolerates_whitespace_only():
    assert _quote_supported("uses   gradient\ndescent", "Logistic regression uses gradient descent.")
    assert not _quote_supported("uses stochastic methods", "Logistic regression uses gradient descent.")


def test_graph_tracks_concepts_across_lectures(course):
    g = GraphRepository()
    gd = _concept(g, "Gradient Descent")
    assert _concept(g, "GD").node_id == gd.node_id  # alias from "Gradient descent (GD)"
    edges = g.edges(STUDENT_A, [COURSE], [gd.node_id], [r.value for r in LECTURE_RELATIONS], "out")
    lectures = g.get_nodes(STUDENT_A, [e.target_node_id for e in edges])
    by_rel = {(e.relation, lectures[e.target_node_id].properties.get("week")) for e in edges}
    assert (Relation.INTRODUCED_IN.value, 2) in by_rel
    assert (Relation.REVISITED_IN.value, 3) in by_rel
    assert gd.properties.get("introduced_week") == 2


def test_every_semantic_and_lecture_edge_has_evidence(course):
    g = GraphRepository()
    rels = [r.value for r in SEMANTIC_RELATIONS | LECTURE_RELATIONS] + [Relation.BUILDS_ON.value]
    edges = g.edges(STUDENT_A, [COURSE], relations=rels)
    assert edges
    evidence = g.evidence_for(STUDENT_A, [e.edge_id for e in edges])
    chunk_ids = {c.chunk_id for c in VectorRepository().list_chunks(ChunkFilter(STUDENT_A, [COURSE]))}
    for e in edges:
        assert evidence.get(e.edge_id), f"{e.relation} edge without provenance"
        assert all(ev.chunk_id in chunk_ids for ev in evidence[e.edge_id])
        assert 0 < e.confidence <= 1


def test_llm_relation_becomes_edge_with_quote(course):
    payload = {"concepts": [], "relations": [
        {"source": "Logistic Regression", "relation": "USES", "target": "Gradient Descent",
         "evidence_quote": "Logistic regression uses gradient descent", "confidence": 0.9}]}
    CourseGraphBuilder(STUDENT_A, COURSE, llm=FakeLLM(payload)).build()
    g = GraphRepository()
    lr, gd = _concept(g, "Logistic Regression"), _concept(g, "Gradient Descent")
    uses = [e for e in g.edges(STUDENT_A, [COURSE], [lr.node_id], [Relation.USES.value]) if e.target_node_id == gd.node_id]
    assert uses
    ev = g.evidence_for(STUDENT_A, [uses[0].edge_id])[uses[0].edge_id]
    assert any(e.quote and "gradient descent" in e.quote.lower() for e in ev)


def test_traversal_is_cycle_safe(db):
    g = GraphRepository()
    ids = [g.upsert_node(STUDENT_A, COURSE, "Concept", k, k.upper()) for k in ("a", "b", "c")]
    for s, t in ((0, 1), (1, 2), (2, 0)):
        g.upsert_edge(STUDENT_A, COURSE, ids[s], "REQUIRES", ids[t], 0.9, "test")
    depth = g.traverse(STUDENT_A, [COURSE], [ids[0]], ["REQUIRES"], max_depth=10)
    assert depth == {ids[1]: 1, ids[2]: 2}
