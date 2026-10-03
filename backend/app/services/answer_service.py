"""Evidence fusion -> grounded answer with citations.

With an LLM configured, the model writes the explanation from numbered evidence only and must
separate (1) what the lectures state, (2) inferred connections, (3) general background.
Without an LLM, a deterministic extractive composer produces the same structure.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional, Sequence

from app.models.graph_models import Relation
from app.models.resource_models import ContentType
from app.models.schemas import QueryResponse, Source
from app.database.academic_repository import get_academic_repo
from app.services.course_scope import courses_mentioned, strip_course_mentions
from app.services.llm_service import get_llm
from app.services.query_router import Intent, Route, RoutedQuery, route_query
from app.services.retrieval_service import Evidence, RetrievalResult, RetrievalService
from app.services.structured_service import answer_structured
from app.services.video_service import format_timestamp

log = logging.getLogger(__name__)

UrlBuilder = Callable[[str, Optional[int], Optional[float]], Optional[str]]

_REL_PHRASES = {
    Relation.INTRODUCED_IN.value: "introduced in",
    Relation.EXPLAINED_IN.value: "explained in",
    Relation.REVISITED_IN.value: "revisited (recap slide) in",
    Relation.BUILDS_ON.value: "builds on",
    Relation.USES.value: "uses",
    Relation.REQUIRES.value: "requires",
    Relation.TYPE_OF.value: "is a type of",
    Relation.EXTENDS.value: "extends",
    Relation.PART_OF.value: "is part of",
    Relation.CONTRASTS_WITH.value: "contrasts with",
    Relation.RELATED_TO.value: "is related to",
    Relation.DERIVED_FROM.value: "is derived from",
    Relation.EXAMPLE_OF.value: "is an example of",
    Relation.APPLIED_IN.value: "is applied in",
    Relation.ASSESSES.value: "assesses",
}


def _phrase(rel: str) -> str:
    return _REL_PHRASES.get(rel, rel.replace("_", " ").lower())


def best_snippet(text: str, terms: Sequence[str], max_chars: int = 280) -> str:
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 2]
    # PDF extraction turns equations into symbol soup; prefer readable prose lines
    readable = [s for s in sents if sum(not ch.isascii() for ch in s) / len(s) < 0.15 and len(s.split()) >= 3]
    sents = readable or sents
    if not sents:
        return text[:max_chars]
    terms = [t.lower() for t in terms if t]
    scored = sorted(
        range(len(sents)),
        key=lambda i: (-sum(t in sents[i].lower() for t in terms), i),
    )
    first = scored[0]
    out = sents[first]
    j = first + 1
    while j < len(sents) and len(out) + len(sents[j]) < max_chars:
        out += " " + sents[j]
        j += 1
    return (out[: max_chars - 1] + "…") if len(out) > max_chars else out


class AnswerService:
    def __init__(self, retrieval: Optional[RetrievalService] = None, url_builder: Optional[UrlBuilder] = None):
        self.retrieval = retrieval or RetrievalService()
        self.url_builder = url_builder or (lambda resource_id, page, t: None)

    # ------------------------------------------------------------------ entry
    def answer(self, user_id: str, course_ids: Sequence[str], query: str, course_id: Optional[str] = None,
               routed: Optional[RoutedQuery] = None, use_llm: bool = True) -> QueryResponse:
        routed = routed or route_query(query)
        if routed.route == Route.STRUCTURED_CANVAS:
            return answer_structured(user_id, course_id, query, routed)
        scope_note = None
        courses = self._courses(user_id)
        named = courses_mentioned(query, courses) & {str(c) for c in course_ids}
        if course_id is None and len(course_ids) > 1:
            if named:
                course_ids = sorted(named)
            else:
                scope_note = ("Searched all your courses with lecture material; name the course "
                              "(e.g. its code) to keep similar courses apart.")
        search_query = strip_course_mentions(query, courses, named) if named else query
        result = self.retrieval.retrieve(user_id, course_ids, search_query, routed)
        if scope_note and len({e.chunk.course_id for e in result.evidence}) > 1:
            result.notes.append(scope_note)
        sources = self._sources(result, query)
        conf = self._confidence(result)
        reply = None
        llm = get_llm() if use_llm else None
        if llm and (result.evidence or result.facts):
            try:
                reply = self._llm_answer(llm, query, result, sources)
            except Exception as e:
                log.warning("LLM answer failed (%s); using extractive answer", type(e).__name__)
        if not reply:
            reply = self._extractive_answer(query, result, sources)
        return QueryResponse(reply=reply, sources=sources, route=routed.route.value, intent=routed.intent.value,
                             confidence=round(conf, 2), notes=result.notes)

    @staticmethod
    def _courses(user_id: str) -> dict[str, dict]:
        try:
            return {str(c["course_id"]): c for c in get_academic_repo().list_courses(user_id)}
        except Exception:
            return {}

    # ------------------------------------------------------------------ sources
    def _sources(self, result: RetrievalResult, query: str) -> list[Source]:
        terms = [c.label for c in result.concepts] + self.retrieval.query_terms(query)
        out = []
        for i, ev in enumerate(result.evidence, 1):
            c = ev.chunk
            is_video = c.content_type == ContentType.TRANSCRIPT
            aligned = c.metadata.get("aligned_slide")
            src_type = "video" if is_video else ("slides" if c.content_type == ContentType.SLIDE else "pdf")
            ts = f"{format_timestamp(c.start_time)}–{format_timestamp(c.end_time)}" if is_video else None
            out.append(Source(
                id=f"S{i}", type=src_type, title=(c.heading or c.resource_title) if not is_video else c.resource_title,
                course_id=c.course_id, week=c.week, module=c.module,
                page=c.page_number, page_end=c.page_end if c.page_end != c.page_number else None,
                start_time=c.start_time, end_time=c.end_time, timestamp=ts,
                url=c.source_url or self.url_builder(c.resource_id, c.page_number, c.start_time),
                snippet=best_snippet(c.text, terms), support=ev.support, relation=ev.reason,
                aligned_slide=(f"{aligned.get('resource_title')} p.{aligned.get('page_number')}" if aligned else None),
            ))
        return out

    def _cite(self, sources: list[Source], chunk_ids: Sequence[str], result: RetrievalResult) -> str:
        idx = {ev.chunk.chunk_id: f"S{i}" for i, ev in enumerate(result.evidence, 1)}
        marks = list(dict.fromkeys(idx[c] for c in chunk_ids if c in idx))
        return (" [" + ", ".join(marks) + "]") if marks else ""

    @staticmethod
    def _label(s: Source) -> str:
        where = f"Week {s.week}" if s.week else (s.module or "")
        if s.type == "video":
            return f"{where} — {s.title} — recording {s.timestamp}"
        page = f"slide {s.page}" + (f"–{s.page_end}" if s.page_end else "") if s.type == "slides" else f"page {s.page}"
        return f"{where} — {s.title} — {page}"

    # ------------------------------------------------------------------ confidence
    @staticmethod
    def _confidence(result: RetrievalResult) -> float:
        routed = result.routed
        dense = sorted((e.score for e in result.evidence if e.support == "direct"), reverse=True)[:3]
        vec = max(0.05, min(0.95, ((sum(dense) / len(dense)) - 0.35) / 0.45)) if dense else 0.05
        facts = [f.edge.confidence for f in result.facts]
        graph = (sum(facts) / len(facts)) * min(1.0, len(result.evidence) / 2) if facts else 0.1
        if routed.route == Route.VECTOR_RAG:
            base = vec
        elif routed.route == Route.GRAPH:
            base = graph if facts else vec * 0.6
        else:
            base = 0.6 * graph + 0.4 * vec if facts else vec * 0.7
        return max(0.05, min(0.97, base * (0.7 + 0.3 * routed.confidence)))

    # ------------------------------------------------------------------ LLM composer
    def _llm_answer(self, llm, query: str, result: RetrievalResult, sources: list[Source]) -> Optional[str]:
        ev_lines = []
        for s, ev in list(zip(sources, result.evidence))[:8]:
            ev_lines.append(f"[{s.id}] ({self._label(s)}; support={s.support}"
                            + (f"; graph link: {s.relation}" if s.relation else "") + f")\n{ev.chunk.text[:700]}")
        fact_lines = [
            f"- {f.source.label} {_phrase(f.edge.relation)} {f.target.label} (confidence {f.edge.confidence:.2f}"
            + (", inferred" if f.inferred else "") + ")"
            for f in result.facts[:25]
        ]
        plan_lines = [f"- {p.get('concept')}: {p.get('lecture') or ('Week ' + str(p['week']) if p.get('week') else '')}"
                      + (" (assessed by the assignment)" if p.get("assessed") else "")
                      + (" (new this week)" if p.get("kind") == "new" else " (recap of earlier week)" if p.get("kind") == "recap" else "")
                      for p in result.plan[:14]]
        s = result.structured or {}
        if s.get("outline"):
            plan_lines.append(f"Week {s['week']} lecture: {s['lecture']}. Slide outline in order: "
                              + "; ".join(f"{o['heading']} (slide {o['page']})" for o in s["outline"][:20]))
            plan_lines.append(f"Only describe Week {s['week']}; do not bring in other weeks' content.")
        if s.get("assignment"):
            plan_lines.append(f"Assignment: {s['assignment']['label']}. Group the needed lectures by week.")
        system = (
            "You are RMIT 1NE, a study assistant answering ONLY from the student's own lecture material.\n"
            "Rules:\n"
            "1. Every course-specific claim must cite evidence markers like [S1]. Never invent markers.\n"
            "2. Use the knowledge-graph facts to explain relationships across lectures; mark relationships "
            "that are flagged 'inferred' as inferred.\n"
            "3. If you add general knowledge not in the evidence, put it in a final section titled "
            "'General background (not from your lectures)'.\n"
            "4. If the evidence does not answer the question, say so plainly.\n"
            "5. Be concise; prefer short paragraphs or bullet lists. Mention weeks, slides and timestamps."
        )
        user = (
            f"Question: {query}\nRoute: {result.routed.route.value} / {result.routed.intent.value}\n\n"
            f"Knowledge-graph facts:\n{chr(10).join(fact_lines) or '(none)'}\n\n"
            f"Ordered course plan:\n{chr(10).join(plan_lines) or '(none)'}\n\n"
            f"Notes: {' '.join(result.notes) or '(none)'}\n\nEvidence:\n" + "\n\n".join(ev_lines)
            + "\n\nNow answer the question in under 200 words using only the evidence above. "
            "End every sentence that uses the evidence with its marker, e.g. 'ReLU outputs max(0, x) [S3].'"
        )
        text = llm.complete(system, user, temperature=0.1).strip()
        valid = {s.id for s in sources}
        text = re.sub(r"\[(S\d+)\]", lambda m: m.group(0) if m.group(1) in valid else "", text)
        if not text:
            return None
        if not re.search(r"\[S\d+\]", text):
            # small local models sometimes ignore the citation rule; never present that as grounded
            evidence = "\n".join(f"• [{s.id}] {self._label(s)}: {s.snippet}" for s in sources[:5] if s.snippet)
            text += ("\n\n(The model did not cite its sources, so treat the text above as unverified. "
                     "The evidence retrieved from your lectures is:)\n" + evidence)
        return text

    # ------------------------------------------------------------------ extractive composer
    def _extractive_answer(self, query: str, result: RetrievalResult, sources: list[Source]) -> str:
        r, intent = result.routed, result.routed.intent
        if not result.evidence and not result.facts:
            return ("I couldn't find anything about that in your ingested lecture material. "
                    + " ".join(result.notes)).strip()
        parts: list[str] = []
        if intent == Intent.WEEK_OVERVIEW and result.structured and "outline" in result.structured:
            parts.append(self._compose_week(result, sources))
        elif intent == Intent.PREREQUISITES or intent == Intent.ASSIGNMENT_REVISION:
            parts.append(self._compose_plan(result, sources))
        elif intent == Intent.CONCEPT_TIMELINE:
            parts.append(self._compose_timeline(result))
        elif intent == Intent.CONCEPT_PROGRESSION and result.plan and "weeks" in result.plan[0]:
            lines = [f"• {p['concept']}: Weeks {', '.join(map(str, p['weeks']))}" + self._cite(sources, p["fact"].evidence_chunk_ids[:1], result)
                     for p in result.plan]
            parts.append("Concepts that recur across your lectures:\n" + "\n".join(lines))
        elif intent == Intent.CONCEPT_PROGRESSION:
            parts.append(self._compose_timeline(result))
        elif intent in (Intent.CONCEPT_RELATION, Intent.LECTURE_CONNECTION):
            parts.append(self._compose_relation(result))
        if intent == Intent.WEEK_OVERVIEW and parts:
            pass
        elif r.route == Route.VECTOR_RAG or (not parts or not parts[0].strip()):
            topic = ", ".join(c.label for c in result.concepts[:2]) or "this"
            lines = [f"• {s.snippet} [{s.id}]" for s in sources[:4] if s.snippet]
            heading = f"Here's what your lecture material says about {topic}:" if r.intent != Intent.LOCATE else f"Where {topic} is discussed in your lectures:"
            if r.intent == Intent.LOCATE:
                lines = [f"• {self._label(s)} [{s.id}]" for s in sources[:5]]
            parts.append(heading + "\n" + "\n".join(lines))
        elif sources:
            lines = [f"• [{s.id}] {self._label(s)}: {s.snippet}" for s in sources[:4] if s.snippet]
            parts.append("Evidence from your lectures:\n" + "\n".join(lines))
        if result.notes:
            parts.append("Note: " + " ".join(result.notes))
        parts.append("(Answer composed directly from your lecture excerpts — no LLM is configured.)")
        return "\n\n".join(p for p in parts if p.strip())

    def _compose_week(self, result: RetrievalResult, sources: list[Source]) -> str:
        s = result.structured
        head = s["lecture"]
        extra = [f"{s['slide_chunks']} slide sections"] + ([f"a {s['recording_minutes']}-minute recording"] if s["recording_minutes"] else [])
        lines = [f"{head} ({', '.join(extra)}). Only material from Week {s['week']} is used below."]
        new = [p for p in result.plan if p.get("kind") == "new"]
        recap = [p for p in result.plan if p.get("kind") == "recap"]
        if new:
            lines.append("\nNew this week:")
            lines += [f"• {p['concept']}{self._cite(sources, p['fact'].evidence_chunk_ids[:1], result)}" for p in new]
        if recap:
            lines.append("\nRecapped from earlier weeks:")
            lines += [f"• {p['concept']} (first taught in Week {p['week']})" for p in recap]
        if s["outline"]:
            lines.append("\nSlide outline:")
            lines += [f"{i}. {o['heading']} (slide {o['page']})" for i, o in enumerate(s["outline"], 1)]
        videos = [x for x in sources if x.type == "video"]
        if videos:
            lines.append("\nIn the recording:")
            lines += [f"• {v.timestamp}: {v.snippet} [{v.id}]" for v in videos[:2] if v.snippet]
        return "\n".join(lines)

    def _compose_plan(self, result: RetrievalResult, sources: list[Source]) -> str:
        lines, n = [], 0
        assessed = [p for p in result.plan if p.get("assessed")]
        if result.structured and result.structured.get("assignment"):
            a = result.structured["assignment"]
            if not assessed:
                lines.append(f"{a['label']}: no lecture concepts could be linked to the spec with enough evidence.")
            else:
                by_lecture: dict[str, list[dict]] = {}
                for p in assessed:
                    by_lecture.setdefault(p.get("lecture") or "Earlier material (not in your ingested lectures)", []).append(p)
                lines.append(f"Lectures you need for {a['label']} (concepts named in the Canvas spec):")
                for lecture, items in sorted(by_lecture.items(), key=lambda kv: kv[1][0].get("week") or 99):
                    cites = "".join(self._cite(sources, p["fact"].evidence_chunk_ids[:1], result) for p in items[:2] if p.get("fact"))
                    lines.append(f"• {lecture}: {', '.join(p['concept'] for p in items)}{cites}")
                spec = [p for p in assessed if p.get("spec_quote")]
                if spec:
                    lines.append("\nWhere the spec asks for them:")
                    lines += [f"• {p['concept']}: “{p['spec_quote'][:160]}”" for p in spec[:5]]
            other = [p for p in result.plan if not p.get("assessed")]
            if other:
                seen_c = {p["concept"] for p in assessed}
                extra = [p for p in other if p["concept"] not in seen_c and not seen_c.add(p["concept"])][:6]
                if extra:
                    lines.append("\nAlso worth revising first (prerequisites of those topics):")
                    lines += [f"• Week {p['week']} — {p['concept']}" if p.get("week") else f"• {p['concept']}" for p in extra]
            return "\n".join(lines)
        targets = ", ".join(c.label for c in result.concepts) or "this topic"
        seen = set()
        ordered = [p for p in result.plan if p["concept"] not in seen and not seen.add(p["concept"])]
        if ordered:
            lines.append(f"Based on your course sequence, revise these {'for the assessment' if assessed else f'before {targets}'}:")
            for p in ordered[:10]:
                n += 1
                where = f"Week {p['week']}" if p.get("week") else "earlier material (not in your ingested lectures)"
                cite = self._cite(sources, p["fact"].evidence_chunk_ids[:1], result) if p.get("fact") else ""
                lines.append(f"{n}. {where} — {p['concept']}{cite}")
        direct = [f for f in result.facts if f.edge.relation not in (Relation.INTRODUCED_IN.value, Relation.EXPLAINED_IN.value) and not f.inferred]
        inferred = [f for f in result.facts if f.inferred]
        if direct:
            lines.append("\nWhy (relationships stated in your lectures):")
            lines += [f"• {f.source.label} {_phrase(f.edge.relation)} {f.target.label}{self._cite(sources, f.evidence_chunk_ids[:1], result)}"
                      for f in _unique_facts(direct)[:8]]
        if inferred:
            lines.append("\nInferred connections (lower certainty):")
            lines += [f"• {f.source.label} {_phrase(f.edge.relation)} {f.target.label}{self._cite(sources, f.evidence_chunk_ids[:1], result)}"
                      for f in _unique_facts(inferred)[:5]]
        return "\n".join(lines)

    def _compose_timeline(self, result: RetrievalResult) -> str:
        if not result.plan:
            return ""
        by_concept: dict[str, list[dict]] = {}
        for p in result.plan:
            by_concept.setdefault(p["concept"], []).append(p)
        out = []
        for concept, items in by_concept.items():
            out.append(f"{concept} in your course:")
            for p in sorted(items, key=lambda x: x.get("week") or 99):
                f = p.get("fact")
                cite = self._cite([], f.evidence_chunk_ids[:1], result) if f else ""
                out.append(f"• {p.get('lecture') or 'Week ' + str(p.get('week'))} — {_phrase(p.get('relation', 'EXPLAINED_IN'))}{cite}")
        return "\n".join(out)

    def _compose_relation(self, result: RetrievalResult) -> str:
        lines = []
        for p in result.plan:
            if p.get("lecture"):
                lines.append(f"• {p['concept']} was introduced in {p['lecture']}"
                             + (self._cite([], p['fact'].evidence_chunk_ids[:1], result) if p.get("fact") else ""))
            elif p.get("shared_by"):
                lines.append(f"• {p['concept']} appears in both Week {p['shared_by'][0]} and Week {p['shared_by'][1]}")
        rel = [f for f in _unique_facts(result.facts) if f.edge.relation not in (Relation.INTRODUCED_IN.value, Relation.EXPLAINED_IN.value, Relation.REVISITED_IN.value)]
        for f in rel[:10]:
            via = f.edge.properties.get("via_concepts")
            extra = f" (recap of {', '.join(via[:4])})" if via else ""
            tag = " (inferred)" if f.inferred else ""
            lines.append(f"• {f.source.label} {_phrase(f.edge.relation)} {f.target.label}{extra}{tag}{self._cite([], f.evidence_chunk_ids[:1], result)}")
        return ("How these connect in your course:\n" + "\n".join(lines)) if lines else ""


def _unique_facts(facts):
    seen, out = set(), []
    for f in facts:
        if f.edge.edge_id not in seen:
            seen.add(f.edge.edge_id)
            out.append(f)
    return out
