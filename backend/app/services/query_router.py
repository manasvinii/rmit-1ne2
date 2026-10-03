"""Deterministic query router: decides which retrieval strategy answers a question.

STRUCTURED_CANVAS  deadlines, enrolled courses, timetable, classmates  -> Canvas/Supabase rows
VECTOR_RAG         "what did the lecturer say about X", "show me where X was discussed"
GRAPH              prerequisites, where a concept was introduced, concept progression
GRAPH_VECTOR       relationship/explanation questions that need graph paths *and* original
                   lecture evidence, and assessment-to-lecture questions
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Route(str, Enum):
    STRUCTURED_CANVAS = "STRUCTURED_CANVAS"
    VECTOR_RAG = "VECTOR_RAG"
    GRAPH = "GRAPH"
    GRAPH_VECTOR = "GRAPH_VECTOR"


class Intent(str, Enum):
    DEADLINE = "deadline"
    COURSE_LIST = "course_list"
    ASSIGNMENT_LIST = "assignment_list"
    GRADES = "grades"
    TIMETABLE = "timetable"
    CLASSMATES = "classmates"
    LECTURE_FACT = "lecture_fact"
    LOCATE = "locate"
    PREREQUISITES = "prerequisites"
    CONCEPT_TIMELINE = "concept_timeline"
    CONCEPT_PROGRESSION = "concept_progression"
    LECTURE_CONNECTION = "lecture_connection"
    CONCEPT_RELATION = "concept_relation"
    ASSIGNMENT_REVISION = "assignment_revision"
    WEEK_OVERVIEW = "week_overview"


@dataclass
class RoutedQuery:
    route: Route
    intent: Intent
    confidence: float
    weeks: list[int] = field(default_factory=list)
    assignment_ref: Optional[str] = None
    reasons: list[str] = field(default_factory=list)


_WEEK = re.compile(r"\b(?:week|wk|lecture|lec|topic)\s*0?(\d{1,2})\b", re.I)
_ASSIGNMENT = re.compile(r"\b(assignment|assessment|project|task|quiz|lab|test|exam)\s*#?\s*(\d+|[a-d])?\b", re.I)
_DEADLINE = re.compile(r"\b(due|deadline|when is|when's|submit|submission|close[sd]?|weight(ing)?|worth|points?|how many marks)\b", re.I)
_STUDY = re.compile(r"\b(revise|revision|review|study|prepare|relevant|cover(ed|s)?|concepts?|topics?|lectures?|need to know|help with|focus on)\b", re.I)
_COURSES = re.compile(r"\b(my courses|which courses|what courses|enrolled|course list|my subjects|my units)\b", re.I)
_ASSIGN_LIST = re.compile(r"\b(my assignments|upcoming assignments|assignments (due|this|next)|what assignments|list (my )?assignments|upcoming (deadlines|assessments))\b", re.I)
_GRADES = re.compile(r"\b(my (grade|grades|marks?|score|scores|results?)|what did i get|gpa|grade forecast)\b", re.I)
_TIMETABLE = re.compile(r"\b(timetable|schedule|class time|when is my class|where is my class|room|what time is)\b", re.I)
_CLASSMATES = re.compile(r"\b(classmates?|study (buddy|group|partner)|peers? in)\b", re.I)
_PREREQ = re.compile(r"\b(prerequisites?|pre-?requisites?|before (learning|studying|tackling|starting|doing|we|i)?|before\b.*\b(lecture|week|topic)|need to (know|understand|learn) (first|before)|foundations? for|required for|depend(s|encies)? on|build up to|should i (revise|review|know|learn) (before|first)|revise before)\b", re.I)
_RELATION = re.compile(r"\b(connect(s|ed|ion)?|relat(e|es|ed|ion|ionship)|link(s|ed)? (to|between|with)|difference between|differ from|compare|comparison|versus|vs\.?|builds? on|lead(s)? to|in relation to)\b", re.I)
_TIMELINE = re.compile(r"\b(first introduced|introduced|where was|which (lecture|week)|when (did|do) we (first )?(learn|cover|see|discuss|talk)|later (applied|used|revisited)|revisited|come(s)? up again)\b", re.I)
_PROGRESSION = re.compile(r"\b(evolve[ds]?|evolution|progress(ion|ed)?|across the (semester|course|lectures)|over the (semester|course)|throughout the (semester|course)|develop(ed)? over)\b", re.I)
_LOCATE = re.compile(r"\b(where (did|does) (my )?(lecturer|professor|tutor|he|she|they)|show (me )?where|timestamp|which slide|what slide|which page|what page|in the (video|recording)|at what time)\b", re.I)
_EXPLAIN = re.compile(r"\b(explain|why|how does|how do|how is|how are|describe|walk me through)\b", re.I)
_OVERVIEW = re.compile(r"\b(covered|cover|taught|teach|discussed|content|contents|topics?|summar(y|ise|ize)|overview|outline|tell me about|what (was|is|were|did we learn) in|what happened in|recap of|go through|about|what'?s new|what is new|new in|learn|learnt|learned)\b", re.I)
_LIST_ONLY = re.compile(r"^\s*(what|which)\s+(concepts?|topics?|lectures?|weeks?)\b", re.I)


def route_query(query: str) -> RoutedQuery:
    q = query.strip()
    weeks = [int(w) for w in _WEEK.findall(q)]
    a = _ASSIGNMENT.search(q)
    assignment_ref = (a.group(0).strip() if a and a.group(2) else (a.group(1) if a else None))
    rq = lambda route, intent, conf, why: RoutedQuery(route, intent, conf, weeks, assignment_ref, [why])

    # --- structured academic data ------------------------------------------------------------
    if a and _DEADLINE.search(q) and not re.search(r"\b(revise|relevant|study|prepare|concepts?|lectures?)\b", q, re.I):
        return rq(Route.STRUCTURED_CANVAS, Intent.DEADLINE, 0.95, "assignment + deadline wording")
    if _ASSIGN_LIST.search(q):
        return rq(Route.STRUCTURED_CANVAS, Intent.ASSIGNMENT_LIST, 0.9, "assignment listing")
    if _COURSES.search(q) and not _STUDY.search(q.replace("courses", "")):
        return rq(Route.STRUCTURED_CANVAS, Intent.COURSE_LIST, 0.9, "enrolled course listing")
    if _GRADES.search(q):
        return rq(Route.STRUCTURED_CANVAS, Intent.GRADES, 0.85, "grade wording")
    if _CLASSMATES.search(q):
        return rq(Route.STRUCTURED_CANVAS, Intent.CLASSMATES, 0.85, "classmate wording")
    if _TIMETABLE.search(q) and not _STUDY.search(q):
        return rq(Route.STRUCTURED_CANVAS, Intent.TIMETABLE, 0.8, "timetable wording")

    # --- assessment -> lecture knowledge -----------------------------------------------------
    if a and _STUDY.search(q):
        return rq(Route.GRAPH_VECTOR, Intent.ASSIGNMENT_REVISION, 0.85, "assignment + study/relevance wording")

    # --- graph questions ---------------------------------------------------------------------
    if _PREREQ.search(q):
        if re.search(r"\brevise|review|explain|why\b", q, re.I) and not _LIST_ONLY.search(q):
            return rq(Route.GRAPH_VECTOR, Intent.PREREQUISITES, 0.85, "prerequisite + revision/explanation")
        return rq(Route.GRAPH, Intent.PREREQUISITES, 0.85, "prerequisite wording")
    if len(set(weeks)) >= 2 and _RELATION.search(q):
        return rq(Route.GRAPH_VECTOR, Intent.LECTURE_CONNECTION, 0.85, "two lectures/weeks + relation wording")
    if len(set(weeks)) == 1 and _OVERVIEW.search(q) and not _LOCATE.search(q) and not _EXPLAIN.search(q):
        return rq(Route.GRAPH_VECTOR, Intent.WEEK_OVERVIEW, 0.85, "one week/lecture + overview wording")
    if _PROGRESSION.search(q):
        return rq(Route.GRAPH, Intent.CONCEPT_PROGRESSION, 0.75, "progression wording")
    if _TIMELINE.search(q) and not _LOCATE.search(q):
        return rq(Route.GRAPH, Intent.CONCEPT_TIMELINE, 0.8, "introduced/revisited wording")
    if _RELATION.search(q):
        return rq(Route.GRAPH_VECTOR, Intent.CONCEPT_RELATION, 0.8, "relation wording")

    # --- lecture content ---------------------------------------------------------------------
    if _LOCATE.search(q):
        return rq(Route.VECTOR_RAG, Intent.LOCATE, 0.8, "asks where/timestamp/slide")
    return rq(Route.VECTOR_RAG, Intent.LECTURE_FACT, 0.7 if _EXPLAIN.search(q) or weeks else 0.6, "default lecture-content question")
