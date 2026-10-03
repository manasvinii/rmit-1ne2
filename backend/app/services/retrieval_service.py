"""Retrieval strategies + evidence fusion.

The graph locates relationships; the vector store supplies the original lecture evidence.
All lookups are scoped to the authenticated user and the courses they are allowed to query.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional, Sequence

from app.database.graph_repository import GraphRepository
from app.database.resource_repository import ResourceRepository
from app.database.vector_repository import ChunkFilter, ScoredChunk, VectorRepository
from app.models.graph_models import (
    LECTURE_RELATIONS,
    PREREQUISITE_RELATIONS,
    SEMANTIC_RELATIONS,
    ExtractionMethod,
    GraphEdge,
    GraphNode,
    NodeType,
    Relation,
)
from app.models.resource_models import ContentChunk
from app.services.embedding_service import Embedder, get_embedder
from app.services.entity_resolution import fuzzy_same, normalize
from app.services.query_router import Intent, Route, RoutedQuery

_STOP = set(
    "a an the of to in on for and or is are was were be been what which who whom how why when where "
    "did do does my me i we our you your about explain lecture lectures lecturer week weeks say said "
    "tell show give based only from with this that these those it its there their they he she taught "
    "learn learned learnt between relate relates related connect connects connection course slide slides "
    "video page time timestamp relevant should before need know concepts concept topic topics".split()
)
_CONCEPT_LABEL_TYPES = [t.value for t in (NodeType.CONCEPT, NodeType.TOPIC, NodeType.METHOD, NodeType.ALGORITHM,
                                          NodeType.FORMULA, NodeType.EXAMPLE)]


@dataclass
class Evidence:
    chunk: ContentChunk
    score: float
    support: str = "direct"  # direct: the chunk itself states it; inferred: linked via graph
    reason: Optional[str] = None


@dataclass
class GraphFact:
    edge: GraphEdge
    source: GraphNode
    target: GraphNode
    evidence_chunk_ids: list[str] = field(default_factory=list)
    evidence_quotes: list[str] = field(default_factory=list)

    @property
    def inferred(self) -> bool:
        methods = set(self.edge.properties.get("methods", [self.edge.extraction_method]))
        return bool(self.edge.properties.get("inferred")) or methods <= {"semantic_similarity", "llm_structured"}

    def sentence(self) -> str:
        rel = self.edge.relation.replace("_", " ").lower()
        return f"{self.source.label} {rel} {self.target.label}"


@dataclass
class RetrievalResult:
    routed: RoutedQuery
    evidence: list[Evidence] = field(default_factory=list)
    facts: list[GraphFact] = field(default_factory=list)
    concepts: list[GraphNode] = field(default_factory=list)
    plan: list[dict] = field(default_factory=list)  # ordered items, e.g. revision plan / timeline
    structured: Optional[dict] = None
    notes: list[str] = field(default_factory=list)


class RetrievalService:
    def __init__(
        self,
        vectors: Optional[VectorRepository] = None,
        graph: Optional[GraphRepository] = None,
        resources: Optional[ResourceRepository] = None,
        embedder: Optional[Embedder] = None,
    ):
        self.vectors = vectors or VectorRepository()
        self.graph = graph or GraphRepository()
        self.resources = resources or ResourceRepository()
        self.embedder = embedder or get_embedder()

    # ================================================================== vector retrieval
    def query_terms(self, query: str) -> list[str]:
        toks = re.findall(r"[A-Za-z][A-Za-z0-9\-]+", query)
        return [t.lower() for t in toks if t.lower() not in _STOP and len(t) > 2]

    def vector_retrieve(
        self, user_id: str, course_ids: Sequence[str], query: str, k: int = 6,
        weeks: Optional[Sequence[int]] = None, extra_terms: Sequence[str] = (),
        resource_ids: Optional[Sequence[str]] = None,
    ) -> list[Evidence]:
        """Hybrid dense + lexical retrieval fused with reciprocal-rank fusion."""
        flt = ChunkFilter(user_id, list(course_ids), weeks=list(weeks) if weeks else None, resource_ids=resource_ids)
        qvec = self.embedder.embed([query])[0]
        dense = self.vectors.vector_search(flt, qvec, k=max(20, k * 3))
        terms = list(dict.fromkeys([*extra_terms, *self.query_terms(query)]))
        lexical = self.vectors.keyword_search(flt, terms, k=max(20, k * 3)) if terms else []
        fused: dict[str, tuple[float, ScoredChunk]] = {}
        for ranked, weight in ((dense, 1.0), (lexical, 0.8)):
            for rank, sc in enumerate(ranked):
                prev = fused.get(sc.chunk.chunk_id)
                rrf = weight / (60 + rank)
                fused[sc.chunk.chunk_id] = ((prev[0] if prev else 0) + rrf, prev[1] if prev else sc)
        dense_score = {sc.chunk.chunk_id: sc.score for sc in dense}
        ordered = sorted(fused.values(), key=lambda t: -t[0])
        out, per_resource = [], defaultdict(int)
        for _, sc in ordered:
            if per_resource[sc.chunk.resource_id] >= max(2, k // 2):
                continue  # diversity across resources (slides vs recording)
            per_resource[sc.chunk.resource_id] += 1
            out.append(Evidence(sc.chunk, dense_score.get(sc.chunk.chunk_id, 0.0)))
            if len(out) >= k:
                break
        return out

    # ================================================================== entity linking
    def link_concepts(self, user_id: str, course_ids: Sequence[str], query: str) -> list[GraphNode]:
        toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", query)
        grams: list[tuple[int, int, str]] = []
        for n in range(min(5, len(toks)), 0, -1):
            for i in range(len(toks) - n + 1):
                words = toks[i : i + n]
                if n == 1 and (words[0].lower() in _STOP or len(words[0]) < 2):
                    continue
                grams.append((i, i + n, " ".join(words)))
        norm_to_span = defaultdict(list)
        for s, e, g in grams:
            norm_to_span[normalize(g)].append((s, e))
        hits = self.graph.find_by_alias(user_id, course_ids, list(norm_to_span))
        matched: list[tuple[int, int, str]] = []
        for norm, node_ids in hits.items():
            for s, e in norm_to_span[norm]:
                for nid in node_ids:
                    matched.append((s, e, nid))
        if not matched:  # typo-tolerant fallback
            aliases = self.graph.list_aliases(user_id, course_ids)
            for s, e, g in grams:
                ng = normalize(g)
                if len(ng) < 6:
                    continue
                for a in aliases:
                    if fuzzy_same(ng, a["alias_norm"], threshold=0.88):
                        matched.append((s, e, a["node_id"]))
        # keep longest non-overlapping spans
        matched.sort(key=lambda m: -(m[1] - m[0]))
        taken: list[tuple[int, int]] = []
        chosen: list[str] = []
        for s, e, nid in matched:
            if any(not (e <= s2 or s >= e2) for s2, e2 in taken) and nid not in chosen:
                continue
            taken.append((s, e))
            if nid not in chosen:
                chosen.append(nid)
        nodes = self.graph.get_nodes(user_id, chosen)
        return [nodes[n] for n in chosen if n in nodes and nodes[n].node_type in _CONCEPT_LABEL_TYPES]

    # ================================================================== graph helpers
    def _facts(self, user_id: str, edges: list[GraphEdge]) -> list[GraphFact]:
        if not edges:
            return []
        nodes = self.graph.get_nodes(user_id, [e.source_node_id for e in edges] + [e.target_node_id for e in edges])
        ev = self.graph.evidence_for(user_id, [e.edge_id for e in edges])
        out = []
        for e in edges:
            if e.source_node_id in nodes and e.target_node_id in nodes:
                evs = ev.get(e.edge_id, [])
                out.append(GraphFact(
                    e, nodes[e.source_node_id], nodes[e.target_node_id],
                    [x.chunk_id for x in evs if x.chunk_id], [x.quote for x in evs if x.quote],
                ))
        return out

    def _lecture_edges(self, user_id, course_ids, concept_ids) -> dict[str, list[GraphFact]]:
        edges = self.graph.edges(user_id, course_ids, concept_ids, [r.value for r in LECTURE_RELATIONS], "out")
        out = defaultdict(list)
        for f in self._facts(user_id, edges):
            out[f.source.node_id].append(f)
        for v in out.values():
            v.sort(key=lambda f: (f.target.properties.get("week") or 99))
        return out

    def _intro(self, facts: list[GraphFact]) -> Optional[GraphFact]:
        intro = [f for f in facts if f.edge.relation == Relation.INTRODUCED_IN.value]
        return intro[0] if intro else (facts[0] if facts else None)

    def _evidence_from_facts(self, user_id: str, facts: list[GraphFact], per_fact: int = 1, support: str = "direct") -> list[Evidence]:
        ids: list[tuple[str, GraphFact]] = []
        for f in facts:
            for cid in f.evidence_chunk_ids[:per_fact]:
                ids.append((cid, f))
        chunks = {c.chunk_id: c for c in self.vectors.get_chunks(user_id, [i for i, _ in ids])}
        out, seen = [], set()
        for cid, f in ids:
            if cid in chunks and cid not in seen:
                seen.add(cid)
                out.append(Evidence(chunks[cid], f.edge.confidence, "inferred" if f.inferred else support, f.sentence()))
        return out

    # ================================================================== graph strategies
    def prerequisites(self, user_id, course_ids, targets: list[GraphNode], res: RetrievalResult, with_vector: bool) -> None:
        target_ids = [t.node_id for t in targets]
        depth = self.graph.traverse(user_id, course_ids, target_ids, [r.value for r in PREREQUISITE_RELATIONS], max_depth=3, min_confidence=0.5)
        sem_edges = self.graph.edges(user_id, course_ids, list(depth) + target_ids, [r.value for r in PREREQUISITE_RELATIONS], "out", 0.5)
        sem_edges = [e for e in sem_edges if e.target_node_id in depth]
        res.facts.extend(self._facts(user_id, sem_edges))

        lec = self._lecture_edges(user_id, course_ids, target_ids)
        prereq_ids = set(depth)
        # concepts the lecturer explicitly recapped at the start of the target's lecture
        for t in targets:
            intro = self._intro(lec.get(t.node_id, []))
            if not intro:
                continue
            week_node = intro.target.node_id
            target_week = intro.target.properties.get("week") or 99
            recapped = self.graph.edges(user_id, course_ids, [week_node], [Relation.REVISITED_IN.value], "in", 0.5)
            for f in self._facts(user_id, recapped):
                if f.source.node_id not in target_ids:
                    prereq_ids.add(f.source.node_id)
                    res.facts.append(f)
            # concepts taught earlier that the target's own lecture explains again (lecturer reuses them)
            reused = self.graph.edges(user_id, course_ids, [week_node], [Relation.EXPLAINED_IN.value], "in", 0.8)
            reused_facts = [
                f for f in self._facts(user_id, reused)
                if f.source.node_id not in target_ids
                and (f.source.properties.get("introduced_week") or 99) < target_week
            ]
            for f in sorted(reused_facts, key=lambda f: -f.edge.confidence)[:6]:
                prereq_ids.add(f.source.node_id)
                res.facts.append(f)
            builds = self.graph.traverse(user_id, course_ids, [week_node], [Relation.BUILDS_ON.value], max_depth=3, min_confidence=0.5)
            lec_edges = self.graph.edges(user_id, course_ids, [week_node, *builds], [Relation.BUILDS_ON.value], "out", 0.5)
            res.facts.extend(self._facts(user_id, lec_edges))

        prereq_ids -= set(target_ids)
        prereq_nodes = self.graph.get_nodes(user_id, list(prereq_ids))
        prereq_lec = self._lecture_edges(user_id, course_ids, list(prereq_ids))
        target_week = min((self._intro(lec.get(t, [])).target.properties.get("week") or 99) if lec.get(t) else 99 for t in target_ids) if target_ids else 99
        # course-wide framework terms (e.g. the Task/Experience/Performance fields on every recap slide)
        # are not specific prerequisites unless the graph links them directly to the target
        all_lectures = {f.target.node_id for facts in prereq_lec.values() for f in facts}
        framework = set()
        for nid, facts in prereq_lec.items():
            spread = len({f.target.node_id for f in facts})
            node = prereq_nodes.get(nid)
            if (node and nid not in depth and node.properties.get("introduced_week") is None
                    and len(all_lectures) >= 4 and spread >= 0.7 * len(all_lectures)):
                framework.add(nid)
                prereq_nodes.pop(nid)
        res.facts = [f for f in res.facts if f.source.node_id not in framework]
        for nid, node in prereq_nodes.items():
            if node.node_type not in _CONCEPT_LABEL_TYPES:
                continue
            intro = self._intro(prereq_lec.get(nid, []))
            week = intro.target.properties.get("week") if intro else None
            res.plan.append({
                "concept": node.label, "node_id": nid, "week": week,
                "lecture": intro.target.label if intro else None,
                "hops": depth.get(nid, 1), "earlier_than_target": week is not None and week <= target_week,
                "fact": intro,
            })
        res.plan.sort(key=lambda p: (p["week"] is None, p["week"] or 99, p["hops"]))
        intro_facts = [p["fact"] for p in res.plan if p["fact"]]
        res.evidence.extend(self._evidence_from_facts(user_id, intro_facts + res.facts, per_fact=1))
        if with_vector:
            for p in res.plan[:5]:
                res.evidence.extend(self.vector_retrieve(user_id, course_ids, p["concept"], k=1,
                                                         weeks=[p["week"]] if p["week"] else None, extra_terms=[p["concept"]]))

    def concept_relation(self, user_id, course_ids, concepts: list[GraphNode], res: RetrievalResult) -> None:
        if len(concepts) < 2:
            return
        a, b = concepts[0], concepts[1]
        path = self._shortest_path(user_id, course_ids, a.node_id, b.node_id)
        if path:
            res.facts.extend(self._facts(user_id, path))
        lec = self._lecture_edges(user_id, course_ids, [a.node_id, b.node_id])
        for c in (a, b):
            intro = self._intro(lec.get(c.node_id, []))
            if intro:
                res.facts.append(intro)
                res.plan.append({"concept": c.label, "week": intro.target.properties.get("week"), "lecture": intro.target.label, "fact": intro})
        weeks_a = {f.target.node_id for f in lec.get(a.node_id, [])}
        weeks_b = {f.target.node_id for f in lec.get(b.node_id, [])}
        shared = weeks_a & weeks_b
        if shared:
            res.notes.append(f"{a.label} and {b.label} are both covered in " + ", ".join(
                sorted({f.target.label for f in lec[a.node_id] if f.target.node_id in shared})))
        if not path:
            res.notes.append(f"No explicit relationship between {a.label} and {b.label} was found in your lecture material.")

    def _shortest_path(self, user_id, course_ids, src: str, dst: str, max_hops: int = 3) -> list[GraphEdge]:
        rels = [r.value for r in SEMANTIC_RELATIONS]
        frontier, prev = deque([(src, 0)]), {src: None}
        while frontier:
            node, d = frontier.popleft()
            if node == dst:
                break
            if d >= max_hops:
                continue
            for e in self.graph.edges(user_id, course_ids, [node], rels, "both", 0.5):
                nxt = e.target_node_id if e.source_node_id == node else e.source_node_id
                if nxt not in prev:
                    prev[nxt] = (node, e)
                    frontier.append((nxt, d + 1))
        if dst not in prev:
            return []
        path, cur = [], dst
        while prev[cur] is not None:
            node, e = prev[cur]
            path.append(e)
            cur = node
        return list(reversed(path))

    def lecture_connection(self, user_id, course_ids, weeks: list[int], res: RetrievalResult,
                           list_shared: bool = True) -> None:
        w1, w2 = sorted(set(weeks))[:2]
        lectures = {n.properties.get("week"): n for n in self.graph.list_nodes(user_id, course_ids, [NodeType.LECTURE.value])}
        l1, l2 = lectures.get(w1), lectures.get(w2)
        if not l1 or not l2:
            res.notes.append(f"Week {w1 if not l1 else w2} has not been ingested, so the connection can't be traced.")
            return
        reach = self.graph.traverse(user_id, course_ids, [l2.node_id], [Relation.BUILDS_ON.value], max_depth=6, min_confidence=0.5)
        if l1.node_id in reach:
            chain = self.graph.edges(user_id, course_ids, [l2.node_id, *reach], [Relation.BUILDS_ON.value], "out", 0.5)
            res.facts.extend(self._facts(user_id, [e for e in chain if e.target_node_id in reach or e.target_node_id == l1.node_id]))
        concept_edges_1 = self.graph.edges(user_id, course_ids, [l1.node_id], [r.value for r in LECTURE_RELATIONS], "in", 0.5)
        concept_edges_2 = self.graph.edges(user_id, course_ids, [l2.node_id], [r.value for r in LECTURE_RELATIONS], "in", 0.5)
        c1 = {e.source_node_id for e in concept_edges_1}
        c2 = {e.source_node_id for e in concept_edges_2}
        cross = self.graph.edges(user_id, course_ids, list(c2), [r.value for r in SEMANTIC_RELATIONS], "out", 0.5)
        res.facts.extend(self._facts(user_id, [e for e in cross if e.target_node_id in c1 and e.source_node_id != e.target_node_id]))
        if list_shared:
            # concepts first taught in the earlier lecture and carried into the later one
            nodes = self.graph.get_nodes(user_id, list(c1 & c2))
            carried = sorted(
                (n for n in nodes.values() if n.properties.get("introduced_week") == w1),
                key=lambda n: n.label,
            )[:6]
            carried_ids = {n.node_id for n in carried}
            res.facts.extend(self._facts(user_id, [e for e in concept_edges_2 if e.source_node_id in carried_ids]))
            res.plan.extend({"concept": n.label, "shared_by": [w1, w2]} for n in carried)
        res.evidence.extend(self._evidence_from_facts(user_id, res.facts, per_fact=1))

    def concept_timeline(self, user_id, course_ids, concepts: list[GraphNode], res: RetrievalResult) -> None:
        lec = self._lecture_edges(user_id, course_ids, [c.node_id for c in concepts])
        for c in concepts:
            for f in lec.get(c.node_id, []):
                res.facts.append(f)
                res.plan.append({"concept": c.label, "week": f.target.properties.get("week"), "lecture": f.target.label,
                                 "relation": f.edge.relation, "fact": f})
        res.evidence.extend(self._evidence_from_facts(user_id, res.facts, per_fact=1))

    def concept_progression(self, user_id, course_ids, res: RetrievalResult, limit: int = 8) -> None:
        concepts = self.graph.list_nodes(user_id, course_ids, _CONCEPT_LABEL_TYPES)
        lec = self._lecture_edges(user_id, course_ids, [c.node_id for c in concepts])
        spans = []
        for c in concepts:
            weeks = sorted({f.target.properties.get("week") for f in lec.get(c.node_id, []) if f.target.properties.get("week")})
            if len(weeks) >= 2:
                spans.append((weeks[-1] - weeks[0], len(weeks), c, weeks))
        spans.sort(key=lambda s: (-s[1], -s[0]))
        for _, _, c, weeks in spans[:limit]:
            facts = lec[c.node_id]
            res.facts.extend(facts)
            res.plan.append({"concept": c.label, "weeks": weeks, "fact": facts[0]})
        res.evidence.extend(self._evidence_from_facts(user_id, [p["fact"] for p in res.plan], per_fact=1))

    def assignment_revision(self, user_id, course_ids, ref: Optional[str], query: str, res: RetrievalResult) -> None:
        assignments = self.graph.list_nodes(user_id, course_ids, [NodeType.ASSIGNMENT.value])
        target = None
        if ref:
            num = re.search(r"(\d+|\b[a-d]\b)$", ref.strip(), re.I)
            for a in assignments:
                label = a.label.lower()
                if num and re.search(rf"\b{re.escape(num.group(1).lower())}\b", label) or normalize(ref) in normalize(label):
                    target = a
                    break
        if not target:
            res.notes.append(
                "I couldn't match that assessment to a synced Canvas assignment, so I searched your lectures for the topic instead."
                if assignments else "No assignments have been synced from Canvas for this course yet."
            )
            res.evidence.extend(self.vector_retrieve(user_id, course_ids, query, k=6))
            return
        assessed = self.graph.edges(user_id, course_ids, [target.node_id], [Relation.ASSESSES.value], "out", 0.4)
        facts = self._facts(user_id, assessed)
        res.facts.extend(facts)
        concepts = [f.target for f in facts]
        if concepts:
            self.prerequisites(user_id, course_ids, concepts, res, with_vector=True)
            lec = self._lecture_edges(user_id, course_ids, [c.node_id for c in concepts])
            quotes = {f.target.node_id: f.evidence_quotes[0] for f in facts
                      if f.evidence_quotes and f.edge.extraction_method == ExtractionMethod.MENTION.value}
            for c in concepts:
                intro = self._intro(lec.get(c.node_id, []))
                res.plan.insert(0, {"concept": c.label, "week": intro.target.properties.get("week") if intro else None,
                                    "lecture": intro.target.label if intro else None, "assessed": True, "fact": intro,
                                    "hops": 0, "spec_quote": quotes.get(c.node_id)})
        else:
            res.notes.append(f"{target.label} has no concepts linked with sufficient evidence; showing semantically similar lecture content.")
            res.evidence.extend(self.vector_retrieve(user_id, course_ids, f"{target.label} {query}", k=6))
        res.structured = {"assignment": {"label": target.label, **target.properties}}

    def week_overview(self, user_id, course_ids, week: int, res: RetrievalResult) -> None:
        """What one week covered: its lecture title, slide outline, new vs recapped concepts, recording.
        Every piece of evidence is restricted to that week."""
        from app.services.graph_extraction_service import heading_to_concept

        lectures = [n for n in self.graph.list_nodes(user_id, course_ids, [NodeType.LECTURE.value])
                    if n.properties.get("week") == week]
        chunks = self.vectors.list_chunks(ChunkFilter(user_id, list(course_ids), weeks=[week]))
        if not lectures and not chunks:
            res.notes.append(f"No lecture material for Week {week} has been ingested.")
            return
        lec_ids = [n.node_id for n in lectures]
        rels = [Relation.INTRODUCED_IN.value, Relation.REVISITED_IN.value]
        facts = [f for f in self._facts(user_id, self.graph.edges(user_id, course_ids, lec_ids, rels, "in", 0.5))
                 if f.source.node_type in _CONCEPT_LABEL_TYPES]
        new = sorted((f for f in facts if f.edge.relation == Relation.INTRODUCED_IN.value),
                     key=lambda f: (-len(f.evidence_chunk_ids), -f.edge.confidence))[:12]
        recapped = [f for f in facts if f.edge.relation == Relation.REVISITED_IN.value
                    and (f.source.properties.get("introduced_week") or 99) < week][:8]

        slides = sorted((c for c in chunks if c.content_type.value in ("slide", "pdf_page")),
                        key=lambda c: (c.resource_id, c.page_number or 0))
        outline, seen = [], set()
        for c in slides:
            topic = heading_to_concept(c.heading)
            if not topic or normalize(topic) in seen:
                continue
            seen.add(normalize(topic))
            outline.append({"heading": c.heading, "page": c.page_number, "chunk_id": c.chunk_id})
        recording = [c for c in chunks if c.content_type.value == "transcript"]
        res.structured = {
            "week": week,
            "lecture": lectures[0].label if lectures else f"Week {week}",
            "outline": outline[:25],
            "slide_chunks": len(slides),
            "recording_minutes": round(max((c.end_time or 0) for c in recording) / 60) if recording else 0,
        }
        res.facts.extend(new + recapped)
        res.plan.extend({"concept": f.source.label, "week": week, "kind": "new", "fact": f} for f in new)
        res.plan.extend({"concept": f.source.label, "week": f.source.properties.get("introduced_week"),
                         "kind": "recap", "fact": f} for f in recapped)
        evidence = self._evidence_from_facts(user_id, new[:6], per_fact=1)
        if recording:
            title = lectures[0].properties.get("title") if lectures else ""
            evidence += self.vector_retrieve(user_id, course_ids, f"{title} overview introduction", k=2, weeks=[week],
                                             resource_ids=list({c.resource_id for c in recording}))
        res.evidence.extend(e for e in evidence if e.chunk.week == week)

    # ================================================================== dispatcher
    def retrieve(self, user_id: str, course_ids: Sequence[str], query: str, routed: RoutedQuery) -> RetrievalResult:
        res = RetrievalResult(routed=routed)
        course_ids = [str(c) for c in course_ids]
        if not course_ids:
            res.notes.append("No lecture material has been ingested for your courses yet.")
            return res
        weeks = routed.weeks or None
        if "this week" in query.lower() and not weeks:
            ingested = sorted({r.week for r in self.resources.list(user_id) if r.week and r.canvas_course_id in course_ids})
            if ingested:
                weeks = [ingested[-1]]
                res.notes.append(f"Interpreting 'this week' as Week {ingested[-1]} (the latest ingested lecture).")

        if routed.route == Route.VECTOR_RAG:
            res.concepts = self.link_concepts(user_id, course_ids, query)
            terms = [c.label for c in res.concepts]
            res.evidence = self.vector_retrieve(user_id, course_ids, query, k=6, weeks=weeks, extra_terms=terms)
            if not res.evidence and weeks:
                res.notes.append(f"Nothing matched within Week {', '.join(map(str, weeks))}; searched all weeks instead.")
                res.evidence = self.vector_retrieve(user_id, course_ids, query, k=6, extra_terms=terms)
            return res

        res.concepts = self.link_concepts(user_id, course_ids, query)
        intent = routed.intent
        if intent == Intent.PREREQUISITES:
            targets = res.concepts
            if not targets and weeks:
                lectures = [n for n in self.graph.list_nodes(user_id, course_ids, [NodeType.LECTURE.value]) if n.properties.get("week") in weeks]
                intro = self.graph.edges(user_id, course_ids, [l.node_id for l in lectures], [Relation.INTRODUCED_IN.value], "in", 0.5)
                targets = list(self.graph.get_nodes(user_id, [e.source_node_id for e in intro]).values())[:8]
            if targets:
                self.prerequisites(user_id, course_ids, targets, res, with_vector=routed.route == Route.GRAPH_VECTOR)
            else:
                res.notes.append("I couldn't identify the topic in your course graph.")
        elif intent == Intent.LECTURE_CONNECTION:
            if len(res.concepts) >= 2:
                self.concept_relation(user_id, course_ids, res.concepts, res)
            self.lecture_connection(user_id, course_ids, routed.weeks, res, list_shared=len(res.concepts) < 2)
        elif intent == Intent.CONCEPT_RELATION:
            self.concept_relation(user_id, course_ids, res.concepts, res)
            if len(res.concepts) < 2:
                res.notes.append("I could only identify one course concept in the question.")
        elif intent == Intent.CONCEPT_TIMELINE:
            if res.concepts:
                self.concept_timeline(user_id, course_ids, res.concepts[:2], res)
            else:
                res.notes.append("I couldn't identify that concept in your course graph.")
        elif intent == Intent.CONCEPT_PROGRESSION:
            if res.concepts:
                self.concept_timeline(user_id, course_ids, res.concepts[:3], res)
            else:
                self.concept_progression(user_id, course_ids, res)
        elif intent == Intent.ASSIGNMENT_REVISION:
            self.assignment_revision(user_id, course_ids, routed.assignment_ref, query, res)
        elif intent == Intent.WEEK_OVERVIEW and weeks:
            if res.concepts:  # "what did we learn about X in week 3" -> that concept, that week only
                res.evidence = self.vector_retrieve(user_id, course_ids, query, k=6, weeks=weeks,
                                                    extra_terms=[c.label for c in res.concepts])
                if not res.evidence:
                    res.notes.append(f"{res.concepts[0].label} doesn't appear in Week {weeks[0]}'s material.")
                return res
            self.week_overview(user_id, course_ids, weeks[0], res)
            res.evidence = _dedupe(res.evidence)
            return res

        if routed.route == Route.GRAPH_VECTOR:
            for c in res.concepts[:3]:
                res.evidence.extend(self.vector_retrieve(user_id, course_ids, f"{c.label}: {query}", k=2, extra_terms=[c.label]))
        if not res.facts and not res.evidence:
            res.notes.append("Falling back to semantic search over your lecture material.")
            res.evidence = self.vector_retrieve(user_id, course_ids, query, k=6, weeks=weeks)
        res.evidence = _dedupe(res.evidence)
        return res


def _dedupe(evidence: list[Evidence], limit: int = 10) -> list[Evidence]:
    seen, out = set(), []
    for e in evidence:
        if e.chunk.chunk_id in seen:
            continue
        seen.add(e.chunk.chunk_id)
        out.append(e)
    return out[:limit]
