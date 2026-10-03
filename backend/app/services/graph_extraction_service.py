"""Builds the evidence-grounded course knowledge graph from ingested lecture chunks.

Pipeline (per user + course):
  1. concept extraction      slide headings, agenda bullets, labelled slide fields, acronym
                             definitions, and (optionally) validated LLM structured output
  2. entity resolution       ConceptRegistry merges case/plural/typo/acronym variants
  3. mention detection       every concept alias is located in every chunk (slides + transcripts)
  4. cross-lecture linking   INTRODUCED_IN / EXPLAINED_IN / REVISITED_IN per week, and
                             Lecture BUILDS_ON Lecture from recap slides
  5. relation extraction     explicit textual cues and slide fields (+ validated LLM relations)
  6. provenance + confidence every edge carries chunk/page/timestamp evidence; confidence is a
                             noisy-OR over independent pieces of evidence
  7. assignment linking      explicit concept mentions in assignment text + semantic similarity

Nothing is added without evidence located in the student's own material.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Optional

from pydantic import ValidationError

from app.core.config import get_settings
from app.database.academic_repository import AcademicRepository, get_academic_repo
from app.database.graph_repository import GraphRepository
from app.database.resource_repository import ResourceRepository
from app.database.vector_repository import ChunkFilter, VectorRepository
from app.models.graph_models import (
    ChunkExtraction,
    EdgeEvidence,
    ExtractionMethod,
    NodeType,
    Relation,
    llm_json_schema,
)
from app.models.resource_models import ContentChunk, ContentType, ResourceType, lecture_key
from app.services.document_service import canonical_heading, is_recap_heading
from app.services.entity_resolution import (
    ConceptRegistry,
    find_acronym_definitions,
    fuzzy_same,
    normalize,
    split_acronym,
)
from app.services.llm_service import LLM, get_llm

log = logging.getLogger(__name__)

PROMPT_VERSION = "kg-extract-v2"
SEED_ALIAS_FILE = Path(__file__).resolve().parent / "data" / "alias_seed.json"

_GENERIC_HEADINGS = {
    "agenda", "outline", "summary", "overview", "introduction", "conclusion", "questions", "question",
    "thank you", "thanks", "reference", "reading", "example", "exercise", "recap", "revision", "review",
    "motivation", "quick recap of last week", "from last week", "pros and con", "practical issue",
    "learning outcome", "today", "next week", "quiz", "activity", "discussion", "notation", "demo",
    "case study", "acknowledgement", "contents", "key takeaway", "takeaway", "q and a", "break",
}
_QUESTION_START = {"why", "how", "when", "where", "which", "who", "can", "do", "does", "is", "are", "should"}
_VERBISH = re.compile(r"\b(can|will|should|does|do|did|is|are|was|were|has|have|fail|fails|works?)\b", re.I)
_SLIDE_FIELD = re.compile(
    r"^\s*(optimi[sz]ation|optimizer|loss(?: function)?|cost(?: function)?|activation(?: function)?|"
    r"regulari[sz]ation|training|learning algorithm)\s*:\s*(.+)$",
    re.I,
)
_FORM_OF = re.compile(r"^\s*(?:a|an|another)\s+(?:form|type|kind|variant)\s+of\s+(.+?)\s*\.?$", re.I)
_FILLER = re.compile(r"\b(basically|just|really|simply|actually|essentially|also|then|so|kind of|sort of|um|uh)\b", re.I)

# (regex over the text *between* two concept mentions, relation, reversed?, base confidence)
_BETWEEN_PATTERNS: list[tuple[re.Pattern, Relation, bool, float]] = [
    (re.compile(r"^(is|are)\s+(a|an)?\s*(type|kind|form|special case|variant|subclass|family)\s+of(\s+(a|an|the))?$"), Relation.TYPE_OF, False, 0.8),
    (re.compile(r"^(is|are)\s+(a|an)?\s*example\s+of(\s+(a|an|the))?$"), Relation.EXAMPLE_OF, False, 0.75),
    (re.compile(r"^(requires?|needs?|depends on|relies on|assumes)(\s+(a|an|the))?$"), Relation.REQUIRES, False, 0.8),
    (re.compile(r"^(is|are)\s+(required|needed|a prerequisite|necessary)\s+for(\s+(a|an|the))?$"), Relation.REQUIRES, True, 0.8),
    (re.compile(r"^(uses?|using|employs?|is trained (with|using|by)|are trained (with|using|by)|trained (with|using|by)|optimi[sz]ed (with|using|by)|with)(\s+(a|an|the))?$"), Relation.USES, False, 0.7),
    (re.compile(r"^(is|are)\s+used\s+(to train|for training|in|by|to optimi[sz]e)(\s+(a|an|the))?$"), Relation.USES, True, 0.75),
    (re.compile(r"^(computes?|calculates?)\s+(the\s+)?gradients?\s+(for|of)(\s+(a|an|the))?$"), Relation.USES, True, 0.75),
    (re.compile(r"^(builds? on|is based on|are based on|based on)(\s+(a|an|the))?$"), Relation.BUILDS_ON, False, 0.8),
    (re.compile(r"^(extends?|generali[sz]es|is an extension of|is a generali[sz]ation of)(\s+(a|an|the))?$"), Relation.EXTENDS, False, 0.8),
    (re.compile(r"^(vs\.?|versus|compared (to|with)|contrasts? with|as opposed to)(\s+(a|an|the))?$"), Relation.CONTRASTS_WITH, False, 0.7),
    (re.compile(r"^(is|are)?\s*(part of|a component of|a step in|a stage of)(\s+(a|an|the))?$"), Relation.PART_OF, False, 0.75),
    (re.compile(r"^(is|are)?\s*derived from(\s+(a|an|the))?$"), Relation.DERIVED_FROM, False, 0.8),
    (re.compile(r"^(looks like|is similar to|are similar to|is like|resembles)(\s+(a|an|the))?$"), Relation.RELATED_TO, False, 0.6),
    (re.compile(r"^(is|are)\s+applied\s+(in|to)(\s+(a|an|the))?$"), Relation.APPLIED_IN, False, 0.7),
]


def noisy_or(confs: Iterable[float], cap: float = 0.97) -> float:
    p = 1.0
    for c in confs:
        p *= 1.0 - max(0.0, min(1.0, c))
    return min(cap, 1.0 - p)


_GERUNDS = {
    "selecting", "choosing", "setting", "using", "constructing", "minimising", "minimizing", "differentiating",
    "regularising", "regularizing", "understanding", "tunning", "tuning", "learning", "training", "computing",
    "interpreting", "measuring", "building", "finding", "evaluating", "applying", "comparing", "introducing",
    "revisiting", "optimising", "optimizing", "defining",
}
_LEAD_PHRASES = re.compile(
    r"^(details of|interpretation of|effect of|problem of|problems with|intuition (behind|for)|"
    r"overview of|introduction to|intro to|more than|types of|kinds of)\s+(the\s+|a\s+|an\s+)?", re.I)
# "Learning Rate", "Training Set": the gerund is part of the term, not a verb to strip
_GERUND_COMPOUNDS = {"rate", "rates", "curve", "curves", "set", "sets", "data", "loss", "error", "errors",
                     "algorithm", "rule", "problem", "time", "phase"}
_TRAIL_WORDS = re.compile(r"\s+(intuition|example|examples|revisited|goal|overview|basics|recap)$", re.I)
_GENERIC_TOKENS = {
    "result", "results", "consideration", "considerations", "important", "alternative", "method", "methods",
    "some", "notation", "detail", "details", "interpretation", "of", "the", "and", "a", "an", "process",
    "prediction", "predictions", "acknowledgment", "acknowledgement", "acknowledgments", "reading", "other",
    "approach", "approaches", "issue", "issues", "summary", "note", "notes", "another", "form", "more",
    "complexity", "final", "complete", "simplified", "question", "questions", "takeaway", "today",
    "intuition", "limitation", "limitations", "advantage", "advantages", "disadvantage", "disadvantages",
    "strength", "strengths", "weakness", "weaknesses", "pros", "cons", "goal", "goals", "terminology",
}


def heading_to_concept(heading: Optional[str]) -> Optional[str]:
    """Return a concept surface form from a slide heading, or None if the heading is generic.

    'Minimising the Loss Function' -> 'Loss Function'; 'Boosting intuition' -> 'Boosting';
    'Recap: Classification - Logistic Regression' -> 'Logistic Regression'; 'Agenda' -> None.
    """
    if not heading:
        return None
    h = canonical_heading(heading) or ""
    h = re.sub(r"\s*\((cont\.?|continued|\d+|simplified|numerical)\)\s*", " ", h, flags=re.I).strip(" :-–")
    h = re.sub(r"^\((simplified|cont\.?)\)\s*", "", h, flags=re.I)
    if re.search(r"\s[-–]\s|[a-z][-–]\s", h):  # "Classification - Logistic Regression"
        h = re.split(r"\s*[-–]\s+", h)[-1]
    m = re.match(r"^what\s+(?:is|are)\s+(?:a|an|the)?\s*(.+?)\s*\??$", h, re.I)
    if m:
        h = m.group(1)
    elif h.endswith("?"):
        return None
    h = _LEAD_PHRASES.sub("", h)
    words = h.split()
    if len(words) >= 2 and words[0].lower() in _GERUNDS and words[1].lower() not in _GERUND_COMPOUNDS:
        words = words[1:]
        while words and words[0].lower() in {"a", "an", "the", "with", "via", "using", "of", "for"}:
            words = words[1:]
        h = " ".join(words)
    h = _TRAIL_WORDS.sub("", h).strip(" :-–")
    link = _HEADING_LINK.match(h)
    if link:  # "Backpropagation via the Chain Rule" -> topic is "Backpropagation"
        h = link.group(1)
    words = h.split()
    if not words or len(words) > 5 or len(h) < 3:
        return None
    if words[0].lower() in _QUESTION_START or words[0].lower().startswith("example"):
        return None
    if _VERBISH.search(h) or re.search(r"\b(for|with|in)\b", h, re.I) and len(words) > 3:
        return None
    if "/" in h or sum(ch.isdigit() for ch in h) > 2 or re.search(r"[^\x00-\x7F]", h):
        return None
    if re.match(r"^(dr|prof|professor|mr|ms|mrs)\.?\s", h, re.I):
        return None
    n = normalize(h)
    if not n or n in _GENERIC_HEADINGS or set(n.split()) <= _GENERIC_TOKENS:
        return None
    return h


_HEADING_LINK = re.compile(r"^(.+?)\s+(via|using|with|through|by)\s+(?:the\s+|a\s+|an\s+)?(.+)$", re.I)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 3]


def _evidence(chunk: ContentChunk, quote: Optional[str], method: ExtractionMethod) -> EdgeEvidence:
    return EdgeEvidence(
        chunk_id=chunk.chunk_id,
        resource_id=chunk.resource_id,
        page_number=chunk.page_number,
        start_time=chunk.start_time,
        end_time=chunk.end_time,
        quote=(quote or "")[:300] or None,
        extraction_method=method.value,
    )


def _quote_supported(quote: str, text: str) -> bool:
    q = re.sub(r"\s+", " ", quote).strip().lower()
    t = re.sub(r"\s+", " ", text).strip().lower()
    if not q:
        return False
    if q in t:
        return True
    m = SequenceMatcher(None, q, t, autojunk=False).find_longest_match(0, len(q), 0, len(t))
    return m.size >= 0.8 * len(q)


def _mentioned_in(name: str, text: str) -> bool:
    """Concept name (or its acronym / a fuzzy variant) occurs in the text."""
    n, t = normalize(name), normalize(text)
    if not n:
        return False
    if f" {n} " in f" {t} ":
        return True
    long_form, acr = split_acronym(name)
    if acr and re.search(rf"\b{re.escape(acr)}s?\b", text):
        return True
    if long_form and long_form != name and normalize(long_form) in t:
        return True
    words = t.split()
    k = len(n.split())
    return any(fuzzy_same(" ".join(words[i:i + k]), n) for i in range(max(0, len(words) - k + 1)))


@dataclass
class _EdgeAcc:
    confs: list[float] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    evidence: list[EdgeEvidence] = field(default_factory=list)
    properties: dict = field(default_factory=dict)

    def add(self, conf: float, method: ExtractionMethod, ev: Optional[EdgeEvidence]) -> None:
        # one vote per distinct chunk so repeated phrases in one slide don't inflate confidence
        if ev is not None and any(e.chunk_id == ev.chunk_id and e.extraction_method == ev.extraction_method for e in self.evidence):
            return
        self.confs.append(conf)
        self.methods.append(method.value)
        if ev is not None:
            self.evidence.append(ev)


class CourseGraphBuilder:
    def __init__(
        self,
        user_id: str,
        course_id: str,
        graph_repo: Optional[GraphRepository] = None,
        vector_repo: Optional[VectorRepository] = None,
        resource_repo: Optional[ResourceRepository] = None,
        academic_repo: Optional[AcademicRepository] = None,
        llm: Optional[LLM] = None,
        use_llm: bool = True,
        embed=None,
    ):
        self.user_id = str(user_id)
        self.course_id = str(course_id)
        self.graph = graph_repo or GraphRepository()
        self.vectors = vector_repo or VectorRepository()
        self.resources = resource_repo or ResourceRepository()
        self.academic = academic_repo
        self.llm = (llm or get_llm()) if use_llm else None
        self.embed = embed
        seed = json.loads(SEED_ALIAS_FILE.read_text()) if SEED_ALIAS_FILE.exists() else {}
        self.seed_aliases: dict[str, str] = seed.get("aliases", {})
        self.registry = ConceptRegistry(seed_aliases=self.seed_aliases)
        self.edges: dict[tuple[str, str, str], _EdgeAcc] = defaultdict(_EdgeAcc)
        self.stats: dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------ public
    def build(self) -> dict:
        chunks = self.vectors.list_chunks(ChunkFilter(self.user_id, [self.course_id]))
        resources = self.resources.list(self.user_id, self.course_id)
        for r in resources:
            title = heading_to_concept(r.metadata.get("deck_title"))
            if title:
                self.registry.add(title, concept_type="Topic")
        heading_concepts, field_mentions, llm_extractions = self._extract_candidates(chunks)
        mentions = self._detect_mentions(chunks)
        admitted = self._admit(mentions, heading_concepts, chunks)

        lectures = self._lecture_index(resources, chunks)
        self._cross_lecture_edges(chunks, mentions, heading_concepts, admitted, lectures)
        self._pattern_relations(chunks, mentions, heading_concepts, admitted)
        self._heading_relations(chunks, admitted)
        self._slide_field_relations(field_mentions, admitted)
        self._llm_relations(chunks, llm_extractions, mentions, heading_concepts, admitted)
        assignment_links = self._assignment_links(admitted, mentions, chunks)
        self._write(resources, lectures, admitted, assignment_links)
        out = {"concepts": len(admitted), **self.stats, **self.graph.stats(self.user_id, self.course_id)}
        log.info("Built graph for course %s: %s", self.course_id, {k: v for k, v in out.items() if k != "nodes"})
        return out

    # ------------------------------------------------------------------ 1. candidates
    def _extract_candidates(self, chunks: list[ContentChunk]):
        heading_concepts: dict[str, str] = {}  # chunk_id -> concept key (slide topic)
        field_mentions: list[tuple[ContentChunk, str, str, str]] = []  # chunk, heading key, field, value
        llm_extractions: dict[str, ChunkExtraction] = {}
        all_text = "\n".join(c.text for c in chunks)

        for c in chunks:
            if c.content_type in (ContentType.SLIDE, ContentType.PDF_PAGE):
                surface = heading_to_concept(c.heading)
                if surface:
                    ctype = "Example" if re.search(r"\b(data|dataset)\b", surface, re.I) else "Concept"
                    heading_concepts[c.chunk_id] = self.registry.add(surface, concept_type=ctype)
                link = _HEADING_LINK.match(canonical_heading(c.heading) or "")
                if link and heading_to_concept(link.group(3)):
                    self.registry.add(heading_to_concept(link.group(3)))
                if normalize(canonical_heading(c.heading) or "") in {"agenda", "outline"}:
                    for line in c.text.split("\n")[1:]:
                        item = re.sub(r"^[\s•▪➢\-\d.)]+", "", line).strip().rstrip(",.;:")
                        concept = heading_to_concept(item) if 1 <= len(item.split()) <= 5 and "->" not in item else None
                        if concept:
                            self.registry.add(concept)
                for line in c.text.split("\n"):
                    m = _SLIDE_FIELD.match(line)
                    if m:
                        for value in re.split(r"\s*(?:\+|,| and )\s*", m.group(2)):
                            value = heading_to_concept(re.sub(r"\(.*?\)", "", value).strip(" .;:")) or ""
                            if 1 <= len(value.split()) <= 4 and not re.search(r"[=∑𝑥𝑦()]", value):
                                field_mentions.append((c, heading_concepts.get(c.chunk_id, ""), m.group(1), value))
                                self.registry.add(value)
        for long_form, acr in find_acronym_definitions(all_text):
            if heading_to_concept(long_form):
                self.registry.add(f"{long_form} ({acr})")
        for alias, target in self.seed_aliases.items():
            key = self.registry.resolve(target)
            if key:
                self.registry.add_alias(key, alias)
        if self.llm:
            for c in chunks:
                ext = self._llm_extract(c)
                if ext:
                    llm_extractions[c.chunk_id] = ext
                    for con in ext.concepts:
                        self.registry.add(con.name, concept_type=con.type, description=con.description, aliases=con.aliases)
        return heading_concepts, field_mentions, llm_extractions

    def _llm_extract(self, chunk: ContentChunk) -> Optional[ChunkExtraction]:
        cache_dir = Path(get_settings().media_cache_dir) / "llm_extractions"
        cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(f"{PROMPT_VERSION}|{self.llm.name}|{chunk.heading}|{chunk.text}".encode()).hexdigest()
        cache = cache_dir / f"{digest}.json"
        if cache.exists():
            try:
                return ChunkExtraction.model_validate_json(cache.read_text())
            except ValidationError:
                cache.unlink()
        system = (
            "You extract an educational knowledge graph from ONE excerpt of a university lecture. "
            "Only use information explicitly stated in the excerpt; never add outside knowledge. "
            "Concepts must be named technical ideas taught in the excerpt. Relations must be directly "
            "supported by a verbatim evidence_quote copied from the excerpt. If unsure, omit it."
        )
        user = (
            f"Lecture heading: {chunk.heading or '(none)'}\nWeek: {chunk.week}\n"
            f"Allowed relations: REQUIRES, BUILDS_ON, USES, EXTENDS, CONTRASTS_WITH, TYPE_OF, PART_OF, "
            f"DERIVED_FROM, EXAMPLE_OF, RELATED_TO, APPLIED_IN (source RELATION target).\n\n"
            f"Excerpt:\n\"\"\"\n{chunk.text[:4000]}\n\"\"\""
        )
        raw = self.llm.complete_json(system, user, llm_json_schema(), "lecture_kg_extraction")
        if raw is None:
            self.stats["llm_failed_chunks"] += 1
            return None
        # validate item by item so one malformed relation can't poison the rest
        concepts, relations = [], []
        from app.models.graph_models import ExtractedConcept, ExtractedRelation

        for c in raw.get("concepts", []) if isinstance(raw, dict) else []:
            try:
                con = ExtractedConcept.model_validate(c)
            except ValidationError:
                self.stats["llm_rejected_concepts"] += 1
                continue
            if not _mentioned_in(con.name, chunk.text):
                self.stats["llm_rejected_concepts"] += 1
                continue
            # aliases from the model's general knowledge would merge concepts the lecture never equated
            con.aliases = [a for a in con.aliases if _mentioned_in(a, chunk.text)]
            concepts.append(con)
        for r in raw.get("relations", []) if isinstance(raw, dict) else []:
            try:
                rel = ExtractedRelation.model_validate(r)
            except ValidationError:
                self.stats["llm_rejected_relations"] += 1
                continue
            if not _quote_supported(rel.evidence_quote, chunk.text):
                self.stats["llm_unsupported_quotes"] += 1
                continue
            if not (_mentioned_in(rel.source, rel.evidence_quote) and _mentioned_in(rel.target, rel.evidence_quote)):
                self.stats["llm_quote_missing_endpoint"] += 1
                continue
            relations.append(rel)
        ext = ChunkExtraction(concepts=concepts[:25], relations=relations[:25])
        cache.write_text(ext.model_dump_json())
        return ext

    # ------------------------------------------------------------------ 3. mentions
    def _alias_patterns(self) -> list[tuple[str, re.Pattern]]:
        pats = []
        for key, entry in self.registry.entries.items():
            for alias_norm, surface in entry.aliases.items():
                if surface.isupper() and 2 <= len(surface) <= 7:  # acronym: case-sensitive
                    pats.append((key, re.compile(rf"(?<![A-Za-z]){re.escape(surface)}s?(?![A-Za-z])")))
                elif len(alias_norm) >= 3:
                    toks = [re.escape(t) for t in alias_norm.split()]
                    body = r"[\s\-]+".join(toks)
                    pats.append((key, re.compile(rf"\b{body}(?:s|es)?\b", re.I)))
        return pats

    def _detect_mentions(self, chunks: list[ContentChunk]) -> dict[str, dict[str, list[tuple[int, int]]]]:
        """chunk_id -> concept key -> [(start, end)] spans in chunk.text"""
        pats = self._alias_patterns()
        out: dict[str, dict[str, list[tuple[int, int]]]] = {}
        surfaces: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        for c in chunks:
            found: dict[str, list[tuple[int, int]]] = defaultdict(list)
            text = c.text.replace("-\n", "").replace("\u2011", "-")
            for key, pat in pats:
                for m in pat.finditer(text):
                    found[key].append(m.span())
            # drop spans fully contained in a longer concept's span ("regression" inside "logistic regression")
            spans = [(s, e, k) for k, v in found.items() for s, e in v]
            kept: dict[str, list[tuple[int, int]]] = defaultdict(list)
            for s, e, k in spans:
                if not any((s2 <= s and e <= e2) and (e2 - s2) > (e - s) and k2 != k for s2, e2, k2 in spans):
                    kept[k].append((s, e))
                    surface = re.sub(r"\s+", " ", text[s:e])
                    if not surface.rstrip("s").isupper():  # acronyms don't vote on the label
                        # slides are edited text; transcripts are ASR output, so slides weigh more
                        weight = 1 if c.content_type == ContentType.TRANSCRIPT else 3
                        surfaces[k][re.sub(r"[\s\-]+", " ", surface.lower())][surface] += weight
            out[c.chunk_id] = {k: sorted(set(v)) for k, v in kept.items()}
        self._relabel(surfaces)
        return out

    def _relabel(self, surfaces) -> None:
        """Display the spelling the material uses most ('Gradient descent' over a 'decent' typo),
        keeping the material's own casing (ReLU, not Relu)."""
        for key, groups in surfaces.items():
            entry = self.registry.entries.get(key)
            if not entry or not groups:
                continue
            totals = {g: sum(raw.values()) for g, raw in groups.items()}
            best = max(totals, key=totals.get)
            current = re.sub(r"[\s\-]+", " ", entry.label.lower())
            if best != current and totals[best] > totals.get(current, 0):
                registered = [s for s in entry.surface_counts if re.sub(r"[\s\-]+", " ", s.lower()) == best]
                raw = max(groups[best], key=groups[best].get)
                entry.label = registered[0] if registered else raw
            if entry.label[:1].islower():
                entry.label = entry.label[0].upper() + entry.label[1:]

    def _admit(self, mentions, heading_concepts, chunks) -> set[str]:
        page_one = {c.chunk_id for c in chunks if c.page_number == 1}
        chunk_count: dict[str, int] = defaultdict(int)
        only_title_pages: dict[str, bool] = defaultdict(lambda: True)
        for cid, per_chunk in mentions.items():
            for k in per_chunk:
                chunk_count[k] += 1
                only_title_pages[k] &= cid in page_one
        heading_count: dict[str, int] = defaultdict(int)
        for k in heading_concepts.values():
            heading_count[k] += 1
        admitted = {
            k for k, e in self.registry.entries.items()
            if ((heading_count[k] >= 1 and (chunk_count[k] + heading_count[k]) >= 2) or chunk_count[k] >= 3
                or (e.concept_type == "Topic" and chunk_count[k] >= 1))
            and not (heading_count[k] == 0 and only_title_pages[k])  # lecturer names, unit codes
        }
        self.stats["candidate_concepts"] = len(self.registry.entries)
        return admitted

    # ------------------------------------------------------------------ 4. lectures + cross-lecture
    def _lecture_index(self, resources, chunks) -> dict[int, dict]:
        lectures: dict[int, dict] = {}
        for r in resources:
            if r.week is None:
                continue
            lec = lectures.setdefault(r.week, {"week": r.week, "resources": [], "title": None, "lecture_number": r.lecture_number})
            lec["resources"].append(r)
            if r.resource_type in (ResourceType.PDF, ResourceType.SLIDES) and not lec["title"]:
                lec["title"] = r.metadata.get("deck_title") or r.title
        for lec in lectures.values():
            lec["title"] = lec["title"] or lec["resources"][0].title
            lec["key"] = lecture_key(self.course_id, lec["week"], lec["title"])
        return lectures

    _DIVIDERS = {"revision", "recap", "quick recap", "quick recap of last week", "review", "from last week",
                 "previously", "last week"}

    def _recap_chunks(self, chunks, mentions, heading_concepts) -> set[str]:
        """Slides that revise earlier material.

        Either the heading says so ('Revision: X', 'Recap: X'), or the slide follows a bare
        'Revision' divider and its topic already appeared in an earlier week's material.
        """
        earliest: dict[str, int] = {}
        for c in chunks:
            if c.week is None:
                continue
            keys = set(mentions.get(c.chunk_id, {})) | ({heading_concepts[c.chunk_id]} if c.chunk_id in heading_concepts else set())
            for k in keys:
                earliest[k] = min(earliest.get(k, 99), c.week)
        recap: set[str] = set()
        by_res: dict[str, list[ContentChunk]] = defaultdict(list)
        for c in chunks:
            if c.content_type in (ContentType.SLIDE, ContentType.PDF_PAGE) and c.week is not None:
                by_res[c.resource_id].append(c)
        for res_chunks in by_res.values():
            in_section = False
            for c in sorted(res_chunks, key=lambda x: x.page_number or 0):
                if is_recap_heading(c.heading):
                    recap.add(c.chunk_id)
                    in_section = True
                    continue
                divider = any(normalize(ln) in self._DIVIDERS for ln in c.text.split("\n")[:12])
                in_section = in_section or divider
                k = heading_concepts.get(c.chunk_id)
                if divider and not k:
                    continue
                if in_section and k and earliest.get(k, 99) < c.week:
                    recap.add(c.chunk_id)
                else:
                    in_section = False
        return recap

    def _cross_lecture_edges(self, chunks, mentions, heading_concepts, admitted, lectures) -> None:
        by_id = {c.chunk_id: c for c in chunks}
        recap_ids = self._recap_chunks(chunks, mentions, heading_concepts)
        self.stats["recap_chunks"] = len(recap_ids)
        # per concept, per week: heading chunks, recap chunks, mention counts
        heading_in: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
        recap_in: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
        mention_in: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
        for cid, per in mentions.items():
            c = by_id[cid]
            if c.week is None:
                continue
            recap = cid in recap_ids
            for k, spans in per.items():
                if k in admitted:
                    (recap_in if recap else mention_in)[k][c.week].extend([cid] * len(spans))
        for cid, k in heading_concepts.items():
            c = by_id[cid]
            if c.week is not None and k in admitted:
                (recap_in if cid in recap_ids else heading_in)[k][c.week].append(cid)

        self.introduced_week: dict[str, int] = {}
        for k in admitted:
            weeks = sorted(set(heading_in[k]) | set(mention_in[k]) | set(recap_in[k]))
            substantive = [w for w in weeks if heading_in[k].get(w) or len(mention_in[k].get(w, [])) >= 3]
            if not substantive:
                continue
            intro = substantive[0]
            earlier_recap = [w for w in recap_in[k] if w <= intro]
            if earlier_recap:
                # first seen on a recap slide: it was introduced before the material we have
                self.stats["introduced_before_material"] += 1
            else:
                self.introduced_week[k] = intro
                ev_ids = (heading_in[k].get(intro) or []) + mention_in[k].get(intro, [])
                self._add_lecture_edge(k, Relation.INTRODUCED_IN, intro, ev_ids, by_id, lectures,
                                       0.9 if heading_in[k].get(intro) else 0.7, ExtractionMethod.HEADING)
            for w in substantive:
                if w == intro and not earlier_recap:
                    continue
                ev_ids = (heading_in[k].get(w) or []) + mention_in[k].get(w, [])
                self._add_lecture_edge(k, Relation.EXPLAINED_IN, w, ev_ids, by_id, lectures,
                                       0.85 if heading_in[k].get(w) else 0.65, ExtractionMethod.HEADING)
            for w, ids in recap_in[k].items():
                self._add_lecture_edge(k, Relation.REVISITED_IN, w, ids, by_id, lectures, 0.85, ExtractionMethod.RECAP)

        # Lecture BUILDS_ON Lecture: a recap slide in week W revisits a concept introduced in week V < W
        for k, per_week in recap_in.items():
            v = self.introduced_week.get(k)
            if v is None:
                continue
            for w, ids in per_week.items():
                if w > v and w in lectures and v in lectures:
                    acc = self.edges[(f"L:{w}", Relation.BUILDS_ON.value, f"L:{v}")]
                    c = by_id[ids[0]]
                    acc.add(0.85, ExtractionMethod.RECAP, _evidence(c, f"{c.heading}", ExtractionMethod.RECAP))
                    acc.properties.setdefault("via_concepts", [])
                    if k not in acc.properties["via_concepts"]:
                        acc.properties["via_concepts"].append(k)

        # Concept APPLIED_IN later lecture: used substantively after being introduced
        # (captured as EXPLAINED_IN above); concept-level progression is answered from these edges.

    def _add_lecture_edge(self, key, rel, week, chunk_ids, by_id, lectures, conf, method) -> None:
        if week not in lectures:
            return
        acc = self.edges[(f"C:{key}", rel.value, f"L:{week}")]
        for cid in list(dict.fromkeys(chunk_ids))[:3]:
            c = by_id[cid]
            acc.add(conf, method, _evidence(c, c.heading or c.text[:160], method))

    # ------------------------------------------------------------------ 5. relations
    def _pattern_relations(self, chunks, mentions, heading_concepts, admitted) -> None:
        for c in chunks:
            per = mentions.get(c.chunk_id, {})
            spans = sorted((s, e, k) for k, v in per.items() if k in admitted for s, e in v)
            text = c.text.replace("-\n", "")
            # explicit "X <cue> Y" within one sentence
            for i, (s1, e1, k1) in enumerate(spans):
                for s2, e2, k2 in spans[i + 1 : i + 4]:
                    if k1 == k2 or s2 - e1 > 60 or s2 < e1:
                        continue
                    between = text[e1:s2]
                    if re.search(r"[.!?\n]", between):
                        continue
                    b = _FILLER.sub(" ", between.lower())
                    b = re.sub(r"[,;:()]", " ", b)
                    b = re.sub(r"\s+", " ", b).strip()
                    for pat, rel, rev, conf in _BETWEEN_PATTERNS:
                        if pat.match(b):
                            src, tgt = (k2, k1) if rev else (k1, k2)
                            quote = self._sentence_around(text, s1, e2)
                            self.edges[(f"C:{src}", rel.value, f"C:{tgt}")].add(
                                conf, ExtractionMethod.PATTERN, _evidence(c, quote, ExtractionMethod.PATTERN)
                            )
                            self.stats["pattern_relations"] += 1
                            break
            # "A form of Y" on a slide whose topic is X  ->  X TYPE_OF Y
            topic = heading_concepts.get(c.chunk_id)
            if topic and topic in admitted:
                for line in text.split("\n"):
                    m = _FORM_OF.match(line)
                    if not m:
                        continue
                    tgt = self.registry.resolve(m.group(1))
                    if tgt and tgt in admitted and tgt != topic:
                        self.edges[(f"C:{topic}", Relation.TYPE_OF.value, f"C:{tgt}")].add(
                            0.7, ExtractionMethod.SLIDE_FIELD, _evidence(c, f"{c.heading}: {line.strip()}", ExtractionMethod.SLIDE_FIELD)
                        )

    def _heading_relations(self, chunks, admitted) -> None:
        """Relations stated by a slide title itself.

        'Backpropagation via the Chain Rule'      -> Backpropagation USES Chain Rule
        'Logistic Regression Gradient Descent'    -> Logistic Regression USES Gradient Descent
        """
        for c in chunks:
            if c.content_type not in (ContentType.SLIDE, ContentType.PDF_PAGE) or not c.heading:
                continue
            h = canonical_heading(c.heading) or ""
            pairs: list[tuple[str, str, float, Relation]] = []
            link = _HEADING_LINK.match(h)
            if link:
                a, b = heading_to_concept(link.group(1)), heading_to_concept(link.group(3))
                ka, kb = (self.registry.resolve(a) if a else None), (self.registry.resolve(b) if b else None)
                if ka and kb:
                    pairs.append((ka, kb, 0.75, Relation.USES))
            else:
                words = h.split()
                for i in range(1, len(words)):
                    ka, kb = self.registry.resolve(" ".join(words[:i])), self.registry.resolve(" ".join(words[i:]))
                    if ka and kb and ka != kb and len(normalize(" ".join(words[i:])).split()) >= 2:
                        # two concept names juxtaposed in a title: related, direction unknown
                        pairs.append((ka, kb, 0.55, Relation.RELATED_TO))
                        break
            for ka, kb, conf, rel in pairs:
                if ka in admitted and kb in admitted and ka != kb:
                    self.edges[(f"C:{ka}", rel.value, f"C:{kb}")].add(
                        conf, ExtractionMethod.HEADING, _evidence(c, c.heading, ExtractionMethod.HEADING)
                    )
                    self.stats["heading_relations"] += 1

    def _slide_field_relations(self, field_mentions, admitted) -> None:
        """'Optimization: Gradient descent' on a slide about X  ->  X USES Gradient descent."""
        for c, topic, field_name, value in field_mentions:
            tgt = self.registry.resolve(value)
            if not topic or topic not in admitted or not tgt or tgt not in admitted or tgt == topic:
                continue
            self.edges[(f"C:{topic}", Relation.USES.value, f"C:{tgt}")].add(
                0.75, ExtractionMethod.SLIDE_FIELD,
                _evidence(c, f"{c.heading} — {field_name}: {value}", ExtractionMethod.SLIDE_FIELD),
            )
            self.stats["slide_field_relations"] += 1

    def _llm_relations(self, chunks, extractions, mentions, heading_concepts, admitted) -> None:
        by_id = {c.chunk_id: c for c in chunks}
        for cid, ext in extractions.items():
            c = by_id[cid]
            present = set(mentions.get(cid, {})) | ({heading_concepts[cid]} if cid in heading_concepts else set())
            for r in ext.relations:
                src, tgt = self.registry.resolve(r.source), self.registry.resolve(r.target)
                # both endpoints must actually occur in this chunk; otherwise it's speculation
                if not src or not tgt or src == tgt or src not in present or tgt not in present:
                    self.stats["llm_relations_dropped"] += 1
                    continue
                admitted.update({src, tgt})
                self.edges[(f"C:{src}", r.relation, f"C:{tgt}")].add(
                    min(0.85, r.confidence) * 0.9, ExtractionMethod.LLM, _evidence(c, r.evidence_quote, ExtractionMethod.LLM)
                )
                self.stats["llm_relations"] += 1

    @staticmethod
    def _sentence_around(text: str, start: int, end: int) -> str:
        left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
        right_candidates = [p for p in (text.find(".", end), text.find("\n", end)) if p != -1]
        right = min(right_candidates) if right_candidates else len(text)
        return text[left : right + 1].strip()

    # ------------------------------------------------------------------ 7. assignments
    def _assignment_links(self, admitted, mentions, chunks) -> list[dict]:
        repo = self.academic or get_academic_repo()
        try:
            assignments = repo.list_assignments(self.user_id, self.course_id)
        except Exception as e:  # academic store unavailable must not block the lecture graph
            log.warning("Assignments unavailable for graph linking: %s", type(e).__name__)
            return []
        if not assignments:
            return []
        chunk_week = {c.chunk_id: c.week for c in chunks}
        weeks_of: dict[str, set] = defaultdict(set)
        for chunk_id, ks in mentions.items():
            for k in ks:
                weeks_of[k].add(chunk_week.get(chunk_id))
        n_weeks = len({w for w in chunk_week.values() if w is not None})
        # course-wide vocabulary ("machine learning", "performance", "task") says nothing about which lecture is needed
        generic = {k for k, ws in weeks_of.items()
                   if n_weeks >= 4 and len(ws) >= 0.7 * n_weeks and self.introduced_week.get(k) is None}
        generic |= {k for k in admitted if k.count(" ") == 0 and len(weeks_of.get(k, ())) >= max(3, 0.5 * n_weeks)}
        pats = [(k, p) for k, p in self._alias_patterns() if k in admitted and k not in generic]
        links = []
        for a in assignments:
            name = a.get("assignment_name") or f"Assignment {a.get('assignment_id')}"
            desc = re.sub(r"<[^>]+>", " ", html.unescape(a.get("description") or ""))
            text = re.sub(r"\s+", " ", f"{name}. {desc}").strip()
            entry = {"assignment": a, "name": name, "text": text, "concepts": {}}
            for k, pat in pats:
                m = pat.search(text)
                if m:
                    quote = self._sentence_around(text, m.start(), m.end())
                    if len(quote) > 300:
                        quote = text[max(0, m.start() - 140): m.end() + 140].strip()
                    entry["concepts"][k] = (0.85, ExtractionMethod.MENTION, quote, None)
            if self.embed and len(desc.split()) >= 8 and not entry["concepts"]:
                # fallback only when the spec names no taught concept explicitly
                vec = self.embed([text[:2000]])[0]
                hits = self.vectors.vector_search(ChunkFilter(self.user_id, [self.course_id]), vec, k=5)
                for h in hits:
                    if h.score < 0.6:
                        continue
                    for k in mentions.get(h.chunk.chunk_id, {}):
                        if k in admitted and k not in generic and k not in entry["concepts"]:
                            entry["concepts"][k] = (round(0.8 * h.score, 3), ExtractionMethod.SEMANTIC, None, h.chunk)
            links.append(entry)
        return links

    # ------------------------------------------------------------------ write
    def _write(self, resources, lectures, admitted, assignment_links) -> None:
        g, u, cid = self.graph, self.user_id, self.course_id
        g.clear_course(u, cid)
        try:
            course = (self.academic or get_academic_repo()).get_course(u, cid) or {}
        except Exception:
            course = {}
        course_label = " ".join(p for p in (course.get("course_code"), course.get("course_name")) if p) or f"Course {cid}"
        course_node = g.upsert_node(u, cid, NodeType.COURSE.value, cid, course_label)
        student_node = g.upsert_node(u, cid, NodeType.STUDENT.value, u, "You")
        g.upsert_edge(u, cid, student_node, Relation.ENROLLED_IN.value, course_node, 1.0, ExtractionMethod.STRUCTURAL.value)

        ids: dict[str, str] = {}
        for week, lec in sorted(lectures.items()):
            nid = g.upsert_node(
                u, cid, NodeType.LECTURE.value, lec["key"], f"Week {week}: {lec['title']}",
                properties={"week": week, "title": lec["title"], "lecture_number": lec["lecture_number"]},
            )
            ids[f"L:{week}"] = nid
            g.upsert_edge(u, cid, course_node, Relation.HAS_LECTURE.value, nid, 1.0, ExtractionMethod.STRUCTURAL.value)
            for r in lec["resources"]:
                rid = g.upsert_node(
                    u, cid, NodeType.RESOURCE.value, r.resource_id, r.title,
                    properties={"resource_id": r.resource_id, "resource_type": r.resource_type.value, "week": week},
                )
                g.upsert_edge(u, cid, nid, Relation.HAS_RESOURCE.value, rid, 1.0, ExtractionMethod.STRUCTURAL.value)

        for key in admitted:
            e = self.registry.entries[key]
            try:
                ntype = NodeType(e.concept_type).value
            except ValueError:
                ntype = NodeType.CONCEPT.value
            nid = g.upsert_node(
                u, cid, ntype, key, e.label, e.description,
                properties={"introduced_week": self.introduced_week.get(key), "surface_forms": sorted(e.surface_counts)},
            )
            ids[f"C:{key}"] = nid
            g.add_aliases(u, cid, nid, [(s, n) for n, s in e.aliases.items()] + [(e.label, key)])

        written = 0
        for (src, rel, tgt), acc in self.edges.items():
            if src not in ids or tgt not in ids or not acc.evidence:
                continue
            props = {**acc.properties, "methods": sorted(set(acc.methods)), "evidence_count": len(acc.evidence)}
            if rel == Relation.BUILDS_ON.value and src.startswith("L:"):
                props["via_concepts"] = [self.registry.entries[k].label for k in props.get("via_concepts", []) if k in self.registry.entries]
            g.upsert_edge(
                u, cid, ids[src], rel, ids[tgt], noisy_or(acc.confs), acc.methods[0], props, acc.evidence[:6]
            )
            written += 1
        self.stats["edges_written"] = written

        for link in assignment_links:
            a = link["assignment"]
            aid = g.upsert_node(
                u, cid, NodeType.ASSIGNMENT.value, str(a.get("assignment_id")), link["name"],
                properties={"due_at": a.get("due_at"), "points_possible": a.get("points_possible"), "html_url": a.get("html_url")},
            )
            g.upsert_edge(u, cid, course_node, Relation.HAS_ASSIGNMENT.value, aid, 1.0, ExtractionMethod.STRUCTURAL.value)
            for key, (conf, method, quote, chunk) in link["concepts"].items():
                if f"C:{key}" not in ids:
                    continue
                ev = (
                    _evidence(chunk, chunk.heading, method) if chunk is not None
                    else EdgeEvidence(chunk_id=None, resource_id=f"assignment:{a.get('assignment_id')}", quote=quote,
                                      extraction_method=method.value)
                )
                g.upsert_edge(u, cid, aid, Relation.ASSESSES.value, ids[f"C:{key}"], conf, method.value,
                              {"inferred": method == ExtractionMethod.SEMANTIC}, [ev])
                g.upsert_edge(u, cid, ids[f"C:{key}"], Relation.ASSESSED_IN.value, aid, conf, method.value,
                              {"inferred": method == ExtractionMethod.SEMANTIC}, [ev])
                self.stats["assignment_links"] += 1


def build_course_graph(user_id: str, course_id: str, **kwargs) -> dict:
    return CourseGraphBuilder(user_id, course_id, **kwargs).build()
