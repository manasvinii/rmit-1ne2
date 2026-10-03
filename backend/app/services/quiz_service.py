"""Brainstorm quizzes: multiple-choice questions written from the student's own lecture slides,
aimed at what an assignment spec asks for (or at one week's new concepts).

Every question cites the slide it was written from. With an LLM the questions are generated and
validated against the cited excerpts; without one they are built deterministically from the slides
(fill-in-the-blank on the defining sentence, and "which lecture introduced X")."""

from __future__ import annotations

import html
import logging
import random
import re
from typing import Callable, Optional, Sequence

from app.database.academic_repository import get_academic_repo
from app.database.graph_repository import GraphRepository
from app.models.graph_models import NodeType
from app.services.answer_service import AnswerService
from app.services.llm_service import get_llm
from app.services.query_router import route_query
from app.services.retrieval_service import RetrievalResult, RetrievalService, _CONCEPT_LABEL_TYPES

log = logging.getLogger(__name__)

_QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer_index": {"type": "integer"},
                    "explanation": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["question", "options", "answer_index", "explanation", "source"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You write multiple-choice revision questions for a university machine-learning student. "
    "Use ONLY the numbered lecture excerpts. Each question must be answerable from the excerpt it cites, "
    "test understanding (not trivia like slide numbers), and have exactly 4 options with one correct answer. "
    "Prefer questions that help with the assignment requirements given. Keep each explanation to one or two sentences. "
    "Never mention excerpt ids like S1 in the question or options; the student cannot see them."
)


# a sentence that says what something is or does, so blanking the concept leaves a real clue
_DEFINING = re.compile(r"\b(is|are|refers to|means|uses|measures|controls|finds|learns|predicts|splits|maps|"
                       r"minimi[sz]es|maximi[sz]es|reduces|separates|combines|consists of)\b", re.I)


class QuizError(ValueError):
    pass


def _strip_html(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


class QuizService:
    def __init__(self, url_builder: Optional[Callable] = None, retrieval: Optional[RetrievalService] = None):
        self.retrieval = retrieval or RetrievalService()
        self.answers = AnswerService(retrieval=self.retrieval, url_builder=url_builder)
        self.graph: GraphRepository = self.retrieval.graph

    # ------------------------------------------------------------------ focus
    def _assignment_focus(self, user_id, course_ids, assignment_id) -> tuple[dict, list[dict]]:
        rows = [a for a in get_academic_repo().list_assignments(user_id)
                if str(a.get("assignment_id")) == str(assignment_id) and str(a.get("course_id")) in set(course_ids)]
        if not rows:
            raise QuizError("That assignment isn't in your synced Canvas courses.")
        a = rows[0]
        name = a.get("assignment_name") or "Assignment"
        res = RetrievalResult(routed=route_query(f"What lectures do I need for {name}?"))
        self.retrieval.assignment_revision(user_id, [str(a["course_id"])], name, name, res)
        items = [p for p in res.plan if p.get("assessed") and p.get("fact")]
        items += [p for p in res.plan if not p.get("assessed") and p.get("fact")]
        info = {"kind": "assignment", "id": str(assignment_id), "name": name, "course_id": str(a["course_id"]),
                "due_at": a.get("due_at"), "spec_excerpt": _strip_html(a.get("description"))[:400]}
        return info, items

    def _week_focus(self, user_id, course_ids, week: int) -> tuple[dict, list[dict]]:
        res = RetrievalResult(routed=route_query(f"What was covered in week {week}?"))
        self.retrieval.week_overview(user_id, course_ids, week, res)
        items = [p for p in res.plan if p.get("kind") == "new" and p.get("fact")]
        lecture = (res.structured or {}).get("lecture", f"Week {week}")
        return {"kind": "week", "week": week, "name": lecture}, items

    # ------------------------------------------------------------------ generation
    def generate(self, user_id: str, course_ids: Sequence[str], assignment_id: Optional[str] = None,
                 week: Optional[int] = None, num_questions: int = 5, use_llm: bool = True) -> dict:
        n = max(1, min(int(num_questions), 10))
        if assignment_id:
            focus, items = self._assignment_focus(user_id, course_ids, assignment_id)
        elif week:
            focus, items = self._week_focus(user_id, course_ids, int(week))
        else:
            raise QuizError("Pick an assignment or a week to build a quiz from.")
        seen, picked = set(), []
        for p in items:
            if p["concept"].lower() not in seen:
                seen.add(p["concept"].lower())
                picked.append(p)
        picked = picked[: max(n, 6)]
        if not picked:
            raise QuizError("No lecture concepts are linked to that yet, so there's nothing to quiz on.")

        facts = [p["fact"] for p in picked]
        evidence = self.retrieval._evidence_from_facts(user_id, facts, per_fact=1)
        sources = self.answers._sources(RetrievalResult(routed=route_query("quiz"), evidence=evidence), "")
        by_chunk = {ev.chunk.chunk_id: (ev.chunk, src) for ev, src in zip(evidence, sources)}
        for p in picked:
            cid = next((c for c in p["fact"].evidence_chunk_ids if c in by_chunk), None)
            p["chunk"], p["source"] = by_chunk.get(cid, (None, None))
        picked = [p for p in picked if p["chunk"] is not None]

        questions, method = [], "slides"
        llm = get_llm() if use_llm else None
        if llm and picked:
            try:
                questions = self._llm_questions(llm, focus, picked, n)
                method = "llm" if questions else method
            except Exception as e:  # any provider/validation failure falls back to slide-built questions
                log.warning("Quiz generation via LLM failed (%s); using slide-built questions", type(e).__name__)
        if len(questions) < n:
            questions += self._slide_questions(user_id, course_ids, picked, n - len(questions),
                                               skip={q["concept"] for q in questions})
        for i, q in enumerate(questions, 1):
            q["id"] = f"q{i}"
        return {
            "focus": focus,
            "concepts": [{"concept": p["concept"], "week": p.get("week"), "lecture": p.get("lecture"),
                          "assessed": bool(p.get("assessed"))} for p in picked],
            "questions": questions[:n],
            "sources": [s.model_dump() for s in sources],
            "method": method,
        }

    def _llm_questions(self, llm, focus: dict, picked: list[dict], n: int) -> list[dict]:
        blocks = []
        for p in picked:
            c, s = p["chunk"], p["source"]
            where = f"Week {c.week}" + (f", slide {c.page_number}" if c.page_number else "")
            need = f" | The assignment asks: \"{p['spec_quote'][:200]}\"" if p.get("spec_quote") else ""
            blocks.append(f"[{s.id}] ({where}; concept: {p['concept']}){need}\n{c.text[:650]}")
        target = (f"Assignment: {focus['name']}. Spec excerpt: {focus.get('spec_excerpt', '')}"
                  if focus["kind"] == "assignment" else f"Lecture: {focus['name']}.")
        user = (f"{target}\n\nLecture excerpts:\n\n" + "\n\n".join(blocks)
                + f"\n\nWrite {n} questions, each on a different concept, as JSON. "
                  "`source` is the excerpt id the question comes from, e.g. \"S2\".")
        data = llm.complete_json(_SYSTEM, user, _QUIZ_SCHEMA, "quiz") or {}
        by_source = {p["source"].id: p for p in picked}
        out, used = [], set()
        for q in data.get("questions") or []:
            opts = [str(o).strip() for o in q.get("options") or [] if str(o).strip()]
            src = str(q.get("source", "")).strip("[] ")
            idx = q.get("answer_index")
            if isinstance(idx, int) and 0 <= idx < len(opts) and len(opts) > 4:  # keep the answer + 3 distractors
                answer = opts[idx]
                opts = [o for o in opts if o != answer][:3]
                opts.insert(min(idx, 3), answer)
                idx = opts.index(answer)
            if src not in by_source or len(opts) != 4 or len(set(o.lower() for o in opts)) != 4:
                log.info("Quiz question rejected: source=%r options=%d", src, len(opts))
                continue
            if not isinstance(idx, int) or not 0 <= idx < 4 or src in used:
                log.info("Quiz question rejected: answer_index=%r duplicate_source=%s", idx, src in used)
                continue
            used.add(src)
            strip_ids = lambda s: re.sub(r"\s*(?:,?\s*(?:as described|as shown|according to|in)\s+)?\[?S\d+\]?", "", s).strip()
            out.append(self._question(by_source[src], strip_ids(q["question"]), opts, idx,
                                      strip_ids(q.get("explanation") or ""), "llm"))
        return out[:n]

    def _slide_questions(self, user_id, course_ids, picked, n, skip=()) -> list[dict]:
        pool = [nd.label for nd in self.graph.list_nodes(user_id, course_ids, _CONCEPT_LABEL_TYPES)]
        lectures = sorted({nd.label for nd in self.graph.list_nodes(user_id, course_ids, [NodeType.LECTURE.value])})
        out = []
        for i, p in enumerate([p for p in picked if p["concept"] not in skip]):
            if len(out) >= n:
                break
            rng = random.Random(p["concept"])
            concept, text = p["concept"], re.sub(r"\s+", " ", p["chunk"].text)
            sentence = next((s for s in re.split(r"(?<=[.!?])\s+|\s*[▪•➢]\s*", text)
                             if len(re.findall(re.escape(concept), s, re.I)) == 1 and 40 <= len(s) <= 260
                             and _DEFINING.search(s)
                             and len(re.sub(re.escape(concept), "", s, flags=re.I).split()) >= 6), None)
            distract = [c for c in pool if c.lower() != concept.lower() and concept.lower() not in c.lower()]
            others = [l for l in lectures if l != p.get("lecture")]

            def cloze():
                if not sentence or len(distract) < 3:
                    return None
                blank = re.sub(re.escape(concept), "_____", sentence, flags=re.I)
                opts = [concept, *rng.sample(distract, 3)]
                rng.shuffle(opts)
                return self._question(p, f"Fill in the blank: “{blank}”", opts, opts.index(concept),
                                      f"The slide says: “{sentence}”", "slides")

            def which_lecture():
                if not p.get("lecture") or not others:
                    return None
                opts = [p["lecture"], *rng.sample(others, min(3, len(others)))]
                rng.shuffle(opts)
                return self._question(p, f"Which lecture introduced {concept}?", opts, opts.index(p["lecture"]),
                                      f"{concept} is first taught in {p['lecture']}.", "slides")

            first, second = (cloze, which_lecture) if i % 2 == 0 else (which_lecture, cloze)
            q = first() or second()
            if q:
                out.append(q)
        return out

    @staticmethod
    def _question(p: dict, question: str, options: list[str], answer_index: int, explanation: str, method: str) -> dict:
        return {
            "question": question, "options": options, "answer_index": answer_index, "explanation": explanation,
            "concept": p["concept"], "week": p.get("week"), "lecture": p.get("lecture"),
            "spec_quote": p.get("spec_quote"), "source_id": p["source"].id if p.get("source") else None,
            "method": method,
        }
