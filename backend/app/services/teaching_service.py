"""Pupil: the student teaches an AI student (Pip, Sage or Milo) and finds the gaps in their own understanding.

The AI student only "knows" the slice of course material the student picked in Setup:
  * ideas to teach  = concepts the knowledge graph says were INTRODUCED_IN the chosen weeks, kept only
                      if their slide/recording/lab evidence lies in the ticked materials
  * grounding       = excerpts retrieved with vector + keyword search filtered to (student, course,
                      weeks, ticked resources); the persona uses them to judge the explanation and
                      ask the next question, never to lecture
  * map hierarchy   = graph relations between the chosen ideas (TYPE_OF, PART_OF, USES, BUILDS_ON ...)

With an LLM configured (local Ollama by default) the persona's replies and the grading are generated;
without one, or if the call fails, a deterministic key-term check keeps the session working.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.api.resources import signed_resource_url
from app.database.academic_repository import get_academic_repo
from app.database.graph_repository import GraphRepository
from app.database.teaching_repository import TeachingRepository
from app.database.vector_repository import ChunkFilter, VectorRepository
from app.models.graph_models import NodeType, Relation
from app.models.resource_models import ContentChunk
from app.services.entity_resolution import fuzzy_same, normalize
from app.services.llm_service import get_llm
from app.services.retrieval_service import _CONCEPT_LABEL_TYPES, _STOP, RetrievalService
from app.services.study_catalog import Scope, StudyCatalog, _course_name, _mmss, weeks_label

log = logging.getLogger(__name__)

MAX_TURN_CHARS = 2000
ATTEMPTS_PER_IDEA = 3
IDEAS_FOR_LENGTH = {10: 4, 15: 5, 25: 7}
VERDICT_STATUS = {"explained": "E", "shaky": "S", "wrong": "G"}
CONFUSION = {None: 5, "G": 4, "S": 2, "E": 0}
CONFUSION_LABEL = {5: "Totally lost", 4: "Very confused", 3: "Confused", 2: "Getting there", 1: "Almost", 0: "Got it!"}
_HIERARCHY = [Relation.TYPE_OF.value, Relation.PART_OF.value, Relation.EXAMPLE_OF.value, Relation.USES.value,
              Relation.BUILDS_ON.value, Relation.REQUIRES.value, Relation.EXTENDS.value]
_NOT_IDEAS = {normalize(w) for w in (
    "application applications introduction overview summary example examples motivation intuition outline "
    "agenda conclusion conclusions recap review definition problem problems solution solutions results "
    "discussion references questions exercise exercises tutorial lab notes background announcements"
).split()}
_GENERIC_TERMS = _STOP | set(
    "also can will may use used using one two new data value values set sets get example examples figure "
    "table thus hence given let first second need non way ways like just make called more most less each "
    "into over such than then very well much many some any all both other only same different".split()
)


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    kind: str
    style: str


PERSONAS = {
    "pip": Persona("pip", "Pip", "the curious kid",
                   "You are about ten years old. You need everything in simple words, ask \"but why?\" a lot, "
                   "and whenever the tutor uses jargon you ask what that word means."),
    "sage": Persona("sage", "Sage", "the sceptic",
                    "You are a sharp, sceptical classmate. You won't accept \"it just works\": you ask for a "
                    "concrete example, for the reason it works, and for when it would fail."),
    "milo": Persona("milo", "Milo", "the mixed-up one",
                    "You are a friendly classmate who already believes something wrong about the current idea. "
                    "You defend that belief once, and only let it go when the tutor clearly explains why it is wrong."),
}

_TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "verdict": {"type": "string", "enum": ["explained", "shaky", "wrong", "not_yet", "off_topic"]},
        "feedback": {"type": "string"},
        "flag": {"type": "string"},
        "notebook": {"type": "string"},
        "source": {"type": "string"},
    },
    "required": ["reply", "verdict", "feedback", "flag", "notebook", "source"],
    "additionalProperties": False,
}


_SMALL_TALK_WORDS = set(
    "hi hii hiii hello helo hey heya hiya yo sup hola gday g'day howdy greetings morning afternoon evening good "
    "there pip sage milo everyone all guys ok okay k kk cool nice great thanks thank thx ty cheers you u yes yeah "
    "yep yup sure alright right um uh hmm so well can hear me test testing mic is this working how are doing "
    "whats what's up ready lets let's go start begin".split()
)
_TUTOR_VOICE = re.compile(
    r"\b(i'?m|i am)\s+(happy|glad|here)\s+to\s+(help|explain)|\blet me explain\b|\bi'?ll explain\b|"
    r"\bas your (tutor|teacher)\b|\bi can (help you|explain)\b", re.I)


def _is_small_talk(text: str) -> bool:
    words = re.findall(r"[a-z']+", text.lower())
    return 0 < len(words) <= 8 and all(w in _SMALL_TALK_WORDS for w in words)


def _speaks_as_tutor(reply: str, persona: Persona) -> bool:
    """The model sometimes swaps roles and greets or teaches its own persona."""
    addressed = re.search(rf"\b(hello|hi|hey|thanks|thank you|okay|ok|sure|great)\b[\s,!.]*{persona.name}\b", reply, re.I)
    return bool(addressed or _TUTOR_VOICE.search(reply))


class SessionNotFound(LookupError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed(session: dict) -> int:
    try:
        start = datetime.fromisoformat(session["started_at"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return 0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return max(0, int((_now() - start).total_seconds()))


def _location(c: ContentChunk) -> str:
    if c.start_time is not None:
        return f"Recording {_mmss(c.start_time)}"
    if c.content_type.value == "notebook":
        return f"Cell {c.page_number}"
    return f"Slide {c.page_number}" if c.content_type.value == "slide" else f"Page {c.page_number}"


def _first_sentence(text: str, limit: int = 170) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    m = re.match(r"(.{20,}?[.!?])\s", text + " ")
    s = m.group(1) if m else text
    return s if len(s) <= limit else s[: limit - 1].rsplit(" ", 1)[0] + "…"


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z0-9\-]{2,}", (text or "").lower()) if t not in _GENERIC_TERMS]


class TeachingService:
    def __init__(self, catalog: Optional[StudyCatalog] = None, retrieval: Optional[RetrievalService] = None,
                 repo: Optional[TeachingRepository] = None):
        self.catalog = catalog or StudyCatalog()
        self.retrieval = retrieval or RetrievalService()
        self.graph: GraphRepository = self.retrieval.graph
        self.vectors: VectorRepository = self.retrieval.vectors
        self.repo = repo or TeachingRepository()

    # ================================================================== ideas from the graph
    def pick_ideas(self, scope: Scope, count: int) -> list[dict]:
        uid, cid = scope.user_id, scope.course_id
        allowed = set(scope.resource_ids)
        lectures = [n for n in self.graph.list_nodes(uid, [cid], [NodeType.LECTURE.value])
                    if n.properties.get("week") in scope.weeks]
        facts = [f for f in self.retrieval._facts(uid, self.graph.edges(
                    uid, [cid], [n.node_id for n in lectures], [Relation.INTRODUCED_IN.value], "in", 0.5))
                 if f.source.node_type in _CONCEPT_LABEL_TYPES]
        chunk_ids = [c for f in facts for c in f.evidence_chunk_ids]
        chunks = {c.chunk_id: c for c in self.vectors.get_chunks(uid, chunk_ids)}

        per_week: dict[int, list[tuple[float, dict]]] = defaultdict(list)
        for f in facts:
            if normalize(f.source.label) in _NOT_IDEAS:
                continue
            week = f.target.properties.get("week")
            grounded = [chunks[c] for c in f.evidence_chunk_ids if c in chunks and chunks[c].resource_id in allowed]
            if not grounded:
                # graph evidence is in an unticked file: keep the concept only if the ticked material covers it
                hits = self.retrieval.vector_retrieve(uid, [cid], f.source.label, k=2, weeks=scope.weeks,
                                                      resource_ids=scope.resource_ids, extra_terms=[f.source.label.lower()])
                grounded = [h.chunk for h in hits if f.source.label.lower() in (h.chunk.text + " " + (h.chunk.heading or "")).lower()]
            if not grounded:
                continue
            name = f.source.label.lower()
            # the slide titled with the idea first; title slides explain nothing
            grounded.sort(key=lambda c: (name not in (c.heading or "").lower(), c.page_number == 1, -len(c.text)))
            score = len(f.evidence_chunk_ids) + f.edge.confidence
            per_week[week].append((score, {"id": f.source.node_id, "name": f.source.label, "week": week,
                                           "node_id": f.source.node_id, "chunks": [c.chunk_id for c in grounded[:3]]}))

        if not per_week:  # graph not built for this material: fall back to the material's own headings
            per_week = self._heading_ideas(scope)

        picked: list[dict] = []
        queues = {w: [i for _, i in sorted(v, key=lambda t: -t[0])] for w, v in per_week.items()}
        while len(picked) < count and any(queues.values()):
            for w in sorted(queues):
                while queues[w]:
                    cand = queues[w].pop(0)
                    if not any(fuzzy_same(cand["name"], p["name"]) or normalize(cand["name"]) == normalize(p["name"])
                               for p in picked):
                        picked.append(cand)
                        break
                if len(picked) >= count:
                    break
        order = {i["id"]: n for n, i in enumerate(picked)}
        picked.sort(key=lambda i: (i["week"] or 0, order[i["id"]]))
        self._attach_parents(uid, cid, picked)
        return picked

    def _heading_ideas(self, scope: Scope) -> dict[int, list[tuple[float, dict]]]:
        from app.services.graph_extraction_service import heading_to_concept

        found: dict[str, dict] = {}
        for c in self.vectors.list_chunks(ChunkFilter(scope.user_id, [scope.course_id], weeks=scope.weeks,
                                                      resource_ids=scope.resource_ids)):
            name = heading_to_concept(c.heading)
            if not name or normalize(name) in _NOT_IDEAS:
                continue
            key = normalize(name)
            item = found.setdefault(key, {"id": "h_" + re.sub(r"\W+", "_", key)[:40], "name": name,
                                          "week": c.week, "node_id": None, "chunks": []})
            item["chunks"].append(c.chunk_id)
        out: dict[int, list[tuple[float, dict]]] = defaultdict(list)
        for item in found.values():
            out[item["week"] or 0].append((float(len(item["chunks"])), {**item, "chunks": item["chunks"][:3]}))
        return out

    def _attach_parents(self, uid: str, cid: str, ideas: list[dict]) -> None:
        ids = {i["node_id"]: i for i in ideas if i.get("node_id")}
        for i in ideas:
            i["parent"] = None
        if len(ids) < 2:
            return
        edges = [e for e in self.graph.edges(uid, [cid], list(ids), _HIERARCHY, "out", 0.5)
                 if e.target_node_id in ids and e.source_node_id != e.target_node_id]
        for e in sorted(edges, key=lambda e: -e.confidence):
            child, parent = ids[e.source_node_id], ids[e.target_node_id]
            if child["parent"] is None and parent["parent"] is None and parent["id"] != child["id"] \
                    and not any(i["parent"] == child["id"] for i in ideas):
                child["parent"] = parent["id"]

    # ================================================================== session lifecycle
    def start(self, user_id: str, course_id: str, weeks: list[int], persona: str, exclude=(), include=(),
              length: int = 15, input_mode: str = "voice", fast: bool = False) -> dict:
        if persona not in PERSONAS:
            raise ValueError("Unknown AI student")
        scope = self.catalog.resolve_scope(user_id, course_id, weeks, exclude, include)
        return self._start(scope, persona, length, input_mode, fast)

    def reteach(self, user_id: str, session_id: str, persona: Optional[str] = None, fast: bool = False) -> dict:
        """New session on the same weeks and ticked material, limited to the ideas that were shaky or gaps."""
        s = self._session(user_id, session_id)
        self.catalog.authorise(user_id, s["course_id"])
        usable = {r.resource_id for r in self.catalog.usable(user_id, s["course_id"])}
        s = {**s, "resource_ids": [r for r in s["resource_ids"] if r in usable]}
        if not s["resource_ids"]:
            raise ValueError("The material from that session is no longer available.")
        persona = persona or s["persona"]
        if persona not in PERSONAS:
            raise ValueError("Unknown AI student")
        summary = s["summary"] or self._summary(s)
        weak = [n["title"] for n in summary["nodes"] if n["status"] in ("G", "S")]
        st = s["state"]
        return self._start(self._scope(s), persona, int(st.get("length", 15)), st.get("input", "voice"),
                           fast or bool(st.get("fast")), focus=weak if persona == s["persona"] else ())

    def _start(self, scope: Scope, persona: str, length: int, input_mode: str, fast: bool, focus=()) -> dict:
        user_id = scope.user_id
        count = IDEAS_FOR_LENGTH.get(length, 5)
        if focus:
            wanted = [normalize(f) for f in focus]
            ideas = [i for i in self.pick_ideas(scope, 50) if normalize(i["name"]) in wanted][:count]
            for i in ideas:
                if not any(p["id"] == i.get("parent") for p in ideas):
                    i["parent"] = None
        else:
            ideas = []
        ideas = ideas or self.pick_ideas(scope, count)
        if not ideas:
            raise ValueError("The selected material has no teachable ideas yet. Tick more material or another week.")
        topics = self.catalog.topics(user_id, scope.course_id)
        for i in ideas:
            i.update({"status": None, "attempts": 0, "hints": 0, "note": None, "time": None, "question": None})
        state = {
            "ideas": ideas, "current": 0, "notebook": [], "length": length, "input": input_mode, "fast": bool(fast),
            "topic": topics.get(scope.weeks[0], scope.label) if len(scope.weeks) == 1 else scope.label,
            "materials": scope.materials, "complete": False,
        }
        if persona == "milo":
            state["misconceptions"] = self._misconceptions(scope, ideas, None if fast else get_llm())
        session = self.repo.create(user_id, scope.course_id, persona, scope.weeks, scope.resource_ids, state)
        opener = self._opener(PERSONAS[persona], state, scope)
        self.repo.add_turn(user_id, session["session_id"], "student", opener, idea_id=ideas[0]["id"])
        ideas[0]["question"] = opener
        self.repo.save_state(user_id, session["session_id"], state)
        return self.view(user_id, session["session_id"])

    def _session(self, user_id: str, session_id: str) -> dict:
        s = self.repo.get(user_id, session_id)
        if not s:
            raise SessionNotFound(session_id)
        return s

    def _scope(self, s: dict) -> Scope:
        return Scope(s["user_id"], s["course_id"], s["weeks"], s["resource_ids"], s["state"].get("materials", []))

    def view(self, user_id: str, session_id: str) -> dict:
        s = self._session(user_id, session_id)
        st = s["state"]
        persona = PERSONAS[s["persona"]]
        course = get_academic_repo().get_course(user_id, s["course_id"]) or {}
        topics = self.catalog.topics(user_id, s["course_id"])
        cur = self._current(st)
        messages = []
        for t in self.repo.turns(user_id, session_id):
            if t["role"] == "me":
                messages.append({"from": "me", "via": t["via"] or "text", "text": t["text"],
                                 "meta": f"You, {'out loud' if t['via'] == 'voice' else 'typed'} · {_mmss(t['at_seconds'])}"})
            elif t["role"] == "flag":
                messages.append({"type": "flag", "text": t["text"]})
            elif t["role"] == "hint":
                messages.append({"type": "hint", "text": t["text"]})
            else:
                messages.append({"from": "student", "text": t["text"]})
        return {
            "id": session_id, "persona": persona.id,
            "subject": {"id": s["course_id"], "code": course.get("course_code") or "",
                        "name": _course_name(course.get("course_name") or "") or f"Course {s['course_id']}",
                        "topics": [topics.get(n) or f"Week {n}" for n in range(1, max([12, *topics]) + 1)]},
            "weeks": s["weeks"], "weeksLabel": weeks_label(s["weeks"]), "topic": st.get("topic"),
            "ideas": self._idea_states(st), "current": cur["id"] if cur else None,
            "confusion": self._confusion(cur), "confusionLabel": CONFUSION_LABEL[self._confusion(cur)],
            "notebook": st.get("notebook", []), "messages": messages,
            "source": self._source_card(s, cur) if cur else None,
            "materials": st.get("materials", []), "complete": st.get("complete", False),
            "secondsTotal": int(st.get("length", 15)) * 60, "elapsed": _elapsed(s), "ended": bool(s["ended_at"]),
            "input": st.get("input", "voice"),
        }

    @staticmethod
    def _current(st: dict) -> Optional[dict]:
        ideas, n = st["ideas"], st.get("current", 0)
        return ideas[n] if n < len(ideas) else None

    @staticmethod
    def _confusion(idea: Optional[dict]) -> int:
        return CONFUSION.get(idea.get("status") if idea else "E", 5)

    def _idea_states(self, st: dict) -> list[dict]:
        out = []
        for n, i in enumerate(st["ideas"]):
            state = "current" if n == st.get("current") and not st.get("complete") else (i["status"] or "todo")
            out.append({"id": i["id"], "name": i["name"], "week": i["week"], "state": state})
        return out

    # ================================================================== a teaching turn
    def turn(self, user_id: str, session_id: str, text: str, via: str = "text") -> dict:
        s = self._session(user_id, session_id)
        if s["ended_at"]:
            raise ValueError("This session has ended")
        text = (text or "").strip()[:MAX_TURN_CHARS]
        if not text:
            raise ValueError("Say or type an explanation first")
        st, persona = s["state"], PERSONAS[s["persona"]]
        idea = self._current(st)
        at = _elapsed(s)
        self.repo.add_turn(user_id, session_id, "me", text, via="voice" if via == "voice" else "text",
                           at_seconds=at, idea_id=idea["id"] if idea else None)
        if idea is None:
            reply = "We've covered everything on my list! Tap \"End and see my map\" to see how it went."
            self.repo.add_turn(user_id, session_id, "student", reply, at_seconds=at)
            return self.view(user_id, session_id)

        if _is_small_talk(text):
            last = next((t for t in reversed(self.repo.turns(user_id, session_id)) if t["role"] == "student"), None)
            again = bool(last and (last.get("assessment") or {}).get("method") == "small_talk")
            reply = self._small_talk_reply(persona, st, idea, again)
            self.repo.add_turn(user_id, session_id, "student", reply, at_seconds=at, idea_id=idea["id"],
                               assessment={"verdict": "not_yet", "feedback": "", "method": "small_talk"})
            out = self.view(user_id, session_id)
            out["method"] = "small_talk"
            return out

        scope = self._scope(s)
        evidence = self._evidence(scope, idea, text)
        nxt = st["ideas"][st["current"] + 1] if st["current"] + 1 < len(st["ideas"]) else None
        history = self.repo.turns(user_id, session_id)[-8:]
        result, method = None, "rules"
        llm = None if st.get("fast") else get_llm()
        if llm is not None and evidence:
            result = self._llm_turn(llm, persona, s, idea, nxt, evidence, history, text)
            method = "llm" if result else "rules"
        if result is None:
            result = self._rules_turn(persona, st, idea, nxt, evidence, text)

        verdict = result["verdict"]
        status = VERDICT_STATUS.get(verdict)
        moved = False
        if status:
            idea["attempts"] += 1
            idea["status"] = status
            idea["note"] = result["feedback"] or idea["note"]
            if status != "E" or idea["time"] is None:
                idea["time"] = at
            moved = status == "E" or idea["attempts"] >= ATTEMPTS_PER_IDEA
        flag = result["flag"].strip()
        if flag and verdict in ("shaky", "wrong", "off_topic"):
            self.repo.add_turn(user_id, session_id, "flag", f"{persona.name} spotted something off: {flag}",
                               at_seconds=at, idea_id=idea["id"])
        reply = result["reply"]
        if moved:
            st["current"] += 1
            if nxt is None:
                st["complete"] = True
            elif status != "E" and normalize(nxt["name"]) not in normalize(reply):
                reply = f"{reply} Hmm, maybe we come back to that. Can you teach me about {nxt['name']} next?"
        if result["notebook"]:
            st["notebook"] = (st.get("notebook", []) + [{"text": result["notebook"][:90], "warn": status in ("S", "G")}])[-6:]
        self.repo.add_turn(user_id, session_id, "student", reply, at_seconds=at, idea_id=idea["id"],
                           assessment={"verdict": verdict, "feedback": result["feedback"], "method": method},
                           evidence=[{k: e[k] for k in ("sid", "chunk_id", "resource_id", "location")} for e in evidence])
        target = st["ideas"][st["current"]] if moved and not st.get("complete") else idea
        target["question"] = reply
        self.repo.save_state(user_id, session_id, st)
        out = self.view(user_id, session_id)
        out["method"] = method
        return out

    @staticmethod
    def _small_talk_reply(persona: Persona, st: dict, idea: dict, again: bool) -> str:
        name = idea["name"]
        if again:
            return {"pip": f"I'm still here! I'm waiting to hear about {name}. What's that all about?",
                    "sage": f"Still waiting. Walk me through {name}, with an example.",
                    "milo": f"Yep, still here. So, about {name}: convince me I've got it wrong."}[persona.id]
        belief = (st.get("misconceptions") or {}).get(idea["id"])
        return {
            "pip": f"Hi! I'm all ears. Can you tell me about {name}? Explain it like I'm ten!",
            "sage": f"Hey. Let's get into it: explain {name} to me, and tell me why it works.",
            "milo": (f"Hi! Fair warning, I still think: {belief.rstrip('.')}. Want to set me straight?"
                     if belief else f"Hi! I think I already get {name}, but go on, explain it to me."),
        }[persona.id]

    def _evidence(self, scope: Scope, idea: dict, text: str, k: int = 4) -> list[dict]:
        own = self.vectors.get_chunks(scope.user_id, idea.get("chunks", []))
        hits = self.retrieval.vector_retrieve(scope.user_id, [scope.course_id], f"{idea['name']}. {text}", k=k,
                                              weeks=scope.weeks, resource_ids=scope.resource_ids,
                                              extra_terms=[idea["name"].lower()])
        chunks, seen = [], set()
        allowed = set(scope.resource_ids)
        for c in [*own[:2], *(h.chunk for h in hits)]:
            if c.chunk_id in seen or c.resource_id not in allowed or c.week not in scope.weeks:
                continue
            seen.add(c.chunk_id)
            chunks.append(c)
        return [{"sid": f"S{n}", "chunk_id": c.chunk_id, "resource_id": c.resource_id, "title": c.resource_title,
                 "location": _location(c), "heading": c.heading or "", "text": c.text[:700], "chunk": c}
                for n, c in enumerate(chunks[:k], start=1)]

    # ------------------------------------------------------------------ LLM persona
    def _llm_turn(self, llm, persona: Persona, s: dict, idea: dict, nxt: Optional[dict], evidence: list[dict],
                  history: list[dict], text: str) -> Optional[dict]:
        st = s["state"]
        course = get_academic_repo().get_course(s["user_id"], s["course_id"]) or {}
        label = weeks_label(s["weeks"])
        misconception = (st.get("misconceptions") or {}).get(idea["id"])
        system = (
            f"You are {persona.name}, {persona.kind}: the STUDENT in this conversation. The person writing to you is "
            f"the TUTOR, a university student teaching you {_course_name(course.get('course_name') or 'their course')}, "
            f"{label}. You are the one who does not understand yet; they are the one explaining. Never call the tutor "
            f"{persona.name}, never greet or thank yourself, never offer to help or explain, never teach the idea. "
            f"Speak as {persona.name}, in the first person, to the tutor. {persona.style}\n"
            + (f"Your current wrong belief about this idea: \"{misconception}\".\n" if misconception else "")
            + "You learn only from what the tutor says. The EXCERPTS are the tutor's own course material: use them "
            "only to judge whether the explanation is correct and complete. Never quote them, never explain the idea "
            "yourself, never give the answer away.\n"
            "Reply rules: stay in character; 1-3 short spoken sentences; end with exactly one question. Ask about the "
            "most important thing the tutor left out, got wrong or said vaguely. If they contradict the excerpts, act "
            f"confused about that exact point. If they talk about something outside the excerpts or {label}, say it "
            "isn't in your notes for those weeks and steer back. If the explanation is correct and covers the key "
            "point, say in your own words what clicked and, if a NEXT IDEA is given, ask about it.\n"
            "Grading (private, for the tutor's report): verdict 'explained' = correct and covers the core of the idea "
            "as the excerpts present it; 'shaky' = partly right, vague, missing the key mechanism or mixing it with "
            "another idea; 'wrong' = incorrect or contradicts the excerpts; 'not_yet' = greeting, question or too "
            "short to judge; 'off_topic' = not about the current idea. feedback = one sentence to the tutor naming "
            "what was missing or wrong and the excerpt id like [S2] (empty for not_yet). flag = max 8 words if the "
            "explanation was vague, mixed two things up or contradicted the material, else empty. notebook = what you "
            "now believe, max 12 words, first-person notes (can be wrong if the tutor was wrong). source = the "
            "excerpt id your question is about."
        )
        convo = "\n".join(f"{persona.name + ' (you)' if t['role'] == 'student' else 'Tutor'}: {t['text']}"
                          for t in history if t["role"] in ("student", "me"))
        excerpts = "\n\n".join(f"[{e['sid']}] {e['title']}, {e['location']}{' - ' + e['heading'] if e['heading'] else ''}\n{e['text']}"
                               for e in evidence)
        done = "; ".join(f"{i['name']}: {i['status'] or 'not yet'}" for i in st["ideas"])
        user = (f"CURRENT IDEA: {idea['name']} (Week {idea['week']})\n"
                f"NEXT IDEA: {nxt['name'] if nxt else 'none, this is the last one'}\n"
                f"Progress: {done}\n\nEXCERPTS:\n{excerpts}\n\nCONVERSATION:\n{convo}\n\nTUTOR JUST SAID: {text}\n\n"
                f"Now write {persona.name}'s reply to the tutor.")
        out = llm.complete_json(system, user, _TURN_SCHEMA, "pupil_turn")
        if not out or not str(out.get("reply") or "").strip():
            return None
        sids = {e["sid"] for e in evidence}
        reply = re.sub(r"\s*\[S\d+\]", "", str(out["reply"])).strip()[:500]
        if _speaks_as_tutor(reply, persona):
            log.info("Discarded a role-swapped %s reply", persona.id)
            return None
        verdict = out.get("verdict") if out.get("verdict") in ("explained", "shaky", "wrong", "not_yet", "off_topic") else "not_yet"
        feedback = str(out.get("feedback") or "").strip()[:300]
        names = {e["sid"]: f"{e['title']}, {e['location']}" for e in evidence}
        feedback = re.sub(r"\[(S\d+)\]", lambda m: f"({names[m.group(1)]})" if m.group(1) in names else "", feedback)
        flag = re.sub(r"\[?\bS\d+\b\]?", "", str(out.get("flag") or "")).strip(" .,:;-")
        flag = flag if len(re.findall(r"[A-Za-z]{3,}", flag)) >= 2 else ""
        return {"reply": reply, "verdict": verdict, "feedback": feedback if verdict in VERDICT_STATUS else "",
                "flag": flag[:80], "notebook": str(out.get("notebook") or "")[:90],
                "source": out.get("source") if out.get("source") in sids else (evidence[0]["sid"] if evidence else "")}

    # ------------------------------------------------------------------ deterministic persona
    def _key_terms(self, idea: dict, evidence: list[dict], n: int = 6) -> list[str]:
        name_terms = set(_terms(idea["name"]))
        counts: Counter = Counter()
        for e in evidence:
            counts.update(t for t in _terms(f"{e['heading']} {e['heading']} {e['text']}") if t not in name_terms)
        return [t for t, c in counts.most_common(n * 2) if c >= 2][:n] or [t for t, _ in counts.most_common(n)]

    def _rules_turn(self, persona: Persona, st: dict, idea: dict, nxt: Optional[dict], evidence: list[dict], text: str) -> dict:
        said = set(_terms(text))
        keys = self._key_terms(idea, evidence)
        hit = [k for k in keys if k in said or any(s.startswith(k[:6]) for s in said if len(k) > 6)]
        missing = next((k for k in keys if k not in hit), None)
        words = len(text.split())
        coverage = len(hit) / max(1, min(len(keys), 4))
        mentions_idea = bool(set(_terms(idea["name"])) & said) or normalize(idea["name"]) in normalize(text)
        if words < 6:
            verdict = "not_yet"
        elif coverage >= 0.5 and words >= 15:
            verdict = "explained"
        elif coverage > 0 or (mentions_idea and words >= 20):
            verdict = "shaky"
        else:
            verdict = "wrong" if idea["attempts"] >= 1 else "shaky"
        src = evidence[0] if evidence else None
        where = f" ({src['title']}, {src['location']})" if src else ""
        if verdict == "explained":
            nxt_q = f" Can you teach me {nxt['name']} next?" if nxt else " I think I've got everything now!"
            reply = {"pip": f"Ohhh, I get it now! It's about {', '.join(hit[:2])}.{nxt_q}",
                     "sage": f"Alright, that holds up. {hit[0].capitalize() if hit else 'That'} was the bit I needed.{nxt_q}",
                     "milo": f"Oh. So I had it backwards about {idea['name']}. That makes way more sense.{nxt_q}"}[persona.id]
            feedback = f"Clear explanation of {idea['name']}: you covered {', '.join(hit[:3])}."
            note = f"{idea['name']}: {', '.join(hit[:3])}"
        elif verdict == "not_yet":
            reply = {"pip": f"Hmm, can you tell me more? What even is {idea['name']}?",
                     "sage": f"That's not an explanation yet. What is {idea['name']}, and why does it work?",
                     "milo": f"Wait, I still think {(st.get('misconceptions') or {}).get(idea['id'], 'I already get it')}. Convince me?"}[persona.id]
            feedback, note = "", ""
        else:
            ask = missing or idea["name"]
            reply = {"pip": f"Wait, what's {ask}? Can you say it without the big words?",
                     "sage": f"Okay, but where does {ask} come in? Give me a concrete example.",
                     "milo": f"Hmm, but I still think {(st.get('misconceptions') or {}).get(idea['id'], 'that is not right')}. Where does {ask} fit in?"}[persona.id]
            feedback = (f"Your explanation of {idea['name']} didn't cover {', '.join(k for k in keys if k not in hit)[:120]}"
                        f"{where}." if keys else f"Your explanation of {idea['name']} was vague{where}.")
            note = f"{idea['name']}?? {ask}??"
        flag = "" if verdict in ("explained", "not_yet") else ("vague, missing the key idea" if coverage == 0 else "only part of the idea")
        return {"reply": reply, "verdict": verdict, "feedback": feedback, "flag": flag, "notebook": note,
                "source": src["sid"] if src else ""}

    def _misconceptions(self, scope: Scope, ideas: list[dict], llm) -> dict[str, str]:
        """One plausible wrong belief per idea for Milo, written against the idea's own excerpt."""
        out = {i["id"]: self._misconception(i, ideas) for i in ideas}
        if llm is None:
            return out
        chunks = {c.chunk_id: c for c in self.vectors.get_chunks(scope.user_id, [i["chunks"][0] for i in ideas if i.get("chunks")])}
        lines = []
        for n, i in enumerate(ideas, start=1):
            c = chunks.get((i.get("chunks") or [None])[0])
            lines.append(f"{n}. {i['name']}: {re.sub(r'\s+', ' ', c.text)[:350] if c else '(no excerpt)'}")
        schema = {"type": "object", "properties": {"beliefs": {"type": "array", "items": {"type": "string"}}},
                  "required": ["beliefs"], "additionalProperties": False}
        got = llm.complete_json(
            "For each numbered idea, write one short, plausible misconception a student might hold about it, "
            "clearly contradicted by the excerpt. First person, max 18 words, no hedging. Return them in order.",
            "\n".join(lines), schema, "milo_beliefs")
        beliefs = [str(b).strip().rstrip(".") for b in (got or {}).get("beliefs", [])]
        for i, b in zip(ideas, beliefs):
            if 3 <= len(b.split()) <= 30:
                out[i["id"]] = b[0].lower() + b[1:] if b[1:2].islower() else b
        return out

    def _misconception(self, idea: dict, ideas: list[dict]) -> str:
        others = [i for i in ideas if i["id"] != idea["id"]]
        same_week = [i for i in others if i["week"] == idea["week"]] or others
        if same_week:
            return f"{idea['name']} is basically the same thing as {same_week[0]['name']}"
        return f"{idea['name']} only matters for really big datasets"

    def _opener(self, persona: Persona, st: dict, scope: Scope) -> str:
        first = st["ideas"][0]["name"]
        label = scope.label
        if persona.id == "pip":
            return f"Hi! I'm Pip. I've got my {label} notes open but I'm totally lost on \"{first}\". Can you explain it like I'm ten?"
        if persona.id == "sage":
            return f"I've skimmed the {label} material and I'm not convinced. What actually is {first}, and why should I believe it works?"
        return f"Oh, {first}! I'm pretty sure I get it already: {st['misconceptions'][st['ideas'][0]['id']]}. Right?"

    # ================================================================== hints and source cards
    def _best_chunk(self, s: dict, idea: dict, video: bool = False) -> Optional[ContentChunk]:
        scope = self._scope(s)
        if not video:
            own = [c for c in self.vectors.get_chunks(s["user_id"], idea.get("chunks", [])) if c.resource_id in scope.resource_ids]
            if own:
                return own[0]
        rids = scope.resource_ids
        if video:
            vids = [c.resource_id for c in self.vectors.list_chunks(
                ChunkFilter(s["user_id"], [s["course_id"]], weeks=scope.weeks, resource_ids=rids, content_types=["transcript"]))]
            rids = list(dict.fromkeys(vids))
            if not rids:
                return None
        hits = self.retrieval.vector_retrieve(s["user_id"], [s["course_id"]], idea["name"], k=1, weeks=scope.weeks,
                                              resource_ids=rids, extra_terms=[idea["name"].lower()])
        return hits[0].chunk if hits else None

    def _source_card(self, s: dict, idea: dict) -> Optional[dict]:
        c = self._best_chunk(s, idea)
        if not c:
            return None
        card = {"title": f"{_location(c)} · {c.heading or idea['name']}", "resource": c.resource_title,
                "url": signed_resource_url(s["user_id"], c.resource_id, c.page_number if c.start_time is None else None, c.start_time),
                "video": None}
        v = self._best_chunk(s, idea, video=True)
        if v is not None:
            card["video"] = {"label": f"Lectorial at {_mmss(v.start_time)}",
                             "url": signed_resource_url(s["user_id"], v.resource_id, None, v.start_time)}
        return card

    def hint(self, user_id: str, session_id: str) -> dict:
        s = self._session(user_id, session_id)
        st = s["state"]
        idea = self._current(st)
        if idea is None:
            return self.view(user_id, session_id)
        c = self._best_chunk(s, idea)
        text = (f"{_location(c)} of {c.resource_title}: {c.heading + ' - ' if c.heading else ''}{_first_sentence(c.text)}"
                if c else f"Try explaining what {idea['name']} is for, then give one example.")
        idea["hints"] = idea.get("hints", 0) + 1
        self.repo.add_turn(user_id, session_id, "hint", text, at_seconds=_elapsed(s), idea_id=idea["id"],
                           evidence=[{"chunk_id": c.chunk_id, "resource_id": c.resource_id}] if c else [])
        self.repo.save_state(user_id, session_id, st)
        return self.view(user_id, session_id)

    # ================================================================== understanding map
    def end(self, user_id: str, session_id: str) -> dict:
        s = self._session(user_id, session_id)
        if s["summary"]:
            return self._with_semester(s, s["summary"])
        summary = self._summary(s)
        self.repo.finish(user_id, session_id, summary)
        return self._with_semester(self._session(user_id, session_id), summary)

    def map(self, user_id: str, session_id: str) -> dict:
        s = self._session(user_id, session_id)
        return self._with_semester(s, s["summary"] or self._summary(s))

    def _summary(self, s: dict) -> dict:
        st, persona = s["state"], PERSONAS[s["persona"]]
        turns = self.repo.turns(s["user_id"], s["session_id"])
        nodes = []
        for i in st["ideas"]:
            status = i["status"] or "N"
            if status == "N":
                c = self._best_chunk(s, i)
                note = (f"This didn't come up. It's in {c.resource_title} ({_location(c)}), so it may be assessed."
                        if c else "This didn't come up in the session.")
            else:
                note = i["note"] or {"E": "You explained this clearly.", "S": "Partly right, but vague.",
                                     "G": "You couldn't explain this yet."}[status]
            if i.get("hints") and status != "N":
                note += f" (You used {i['hints']} hint{'s' if i['hints'] > 1 else ''}.)"
            c = self._best_chunk(s, i) if status != "N" else None
            nodes.append({"id": i["id"], "title": i["name"], "week": i["week"], "status": status, "note": note,
                          "time": _mmss(i["time"]) if i["time"] is not None else None, "parent": i.get("parent"),
                          "source": {"label": f"{c.resource_title}, {_location(c)}",
                                     "url": signed_resource_url(s["user_id"], c.resource_id,
                                                                c.page_number if c.start_time is None else None,
                                                                c.start_time)} if c else None})
        issues = [{"status": n["status"], "title": n["title"], "text": n["note"], "time": n["time"] or "",
                   "source": n["source"]} for n in sorted(nodes, key=lambda n: {"G": 0, "S": 1}.get(n["status"], 2))
                  if n["status"] in ("G", "S")]
        toughest = None
        rank = {"wrong": 0, "shaky": 1, "off_topic": 2}
        prev_question = None
        worst = 9
        for t in turns:
            if t["role"] == "student":
                v = (t["assessment"] or {}).get("verdict")
                if v in rank and prev_question and rank[v] < worst:
                    worst, toughest = rank[v], prev_question
                prev_question = t["text"] if t["text"].strip().endswith("?") else prev_question
        if toughest is None:
            asked = [t["text"] for t in turns if t["role"] == "student" and t["text"].strip().endswith("?")]
            toughest = asked[-1] if asked else None
        last = max((t["at_seconds"] for t in turns), default=0)
        landed = sum(1 for n in nodes if n["status"] == "E")
        root_title = st.get("topic") or weeks_label(s["weeks"])
        return {
            "sessionId": s["session_id"], "persona": persona.id, "courseId": s["course_id"], "weeks": s["weeks"],
            "weeksLabel": weeks_label(s["weeks"]), "topic": st.get("topic"),
            "root": {"title": root_title, "sub": f"{weeks_label(s['weeks'])} topic" if len(s["weeks"]) == 1 else "Mixed revision"},
            "nodes": nodes, "issues": issues, "toughestQuestion": toughest, "landed": landed, "total": len(nodes),
            "minutes": max(1, round(last / 60)) if last else 0,
            "weakSpots": [n["id"] for n in nodes if n["status"] in ("G", "S")][:3],
            "materials": st.get("materials", []),
        }

    def _with_semester(self, s: dict, summary: dict) -> dict:
        course = get_academic_repo().get_course(s["user_id"], s["course_id"]) or {}
        subject = self.catalog.subject(s["user_id"], s["course_id"], course, self.progress(s["user_id"], s["course_id"])) or {}
        strip = list(subject.get("progress") or "")
        for w in s["weeks"]:
            if 0 < w <= len(strip):
                strip[w - 1] = "T"
        return {**summary, "semester": "".join(strip),
                "subject": {"id": s["course_id"], "name": subject.get("name") or "", "code": subject.get("code") or ""}}

    # ================================================================== progress across sessions
    def progress(self, user_id: str, course_id: str) -> dict[int, str]:
        """Week -> E/S/G from the most recent finished session that covered that week."""
        out: dict[int, str] = {}
        for s in self.repo.list(user_id, course_id):
            if not s["summary"]:
                continue
            by_week: dict[int, list[str]] = defaultdict(list)
            for n in s["summary"].get("nodes", []):
                if n.get("week") and n["status"] != "N":
                    by_week[n["week"]].append(n["status"])
            for w, sts in by_week.items():
                if w not in out:  # list() is newest first
                    out[w] = "G" if "G" in sts else "S" if "S" in sts else "E"
        return out

    def gaps(self, user_id: str, limit: int = 6) -> list[dict]:
        out, seen = [], set()
        names = {str(c["course_id"]): _course_name(c.get("course_name") or "") for c in get_academic_repo().list_courses(user_id)}
        for s in self.repo.list(user_id):
            for n in (s["summary"] or {}).get("nodes", []):
                key = (s["course_id"], normalize(n["title"]))
                if n["status"] in ("G", "S") and key not in seen:
                    seen.add(key)
                    out.append({"concept": n["title"], "subjectId": s["course_id"], "subjectName": names.get(s["course_id"], ""),
                                "week": n.get("week"), "persona": s["persona"], "status": n["status"]})
        return sorted(out, key=lambda g: g["status"] != "G")[:limit]
