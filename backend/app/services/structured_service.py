"""STRUCTURED_CANVAS route: answers from the synced Canvas tables (no RAG, no graph).

If N8N_WEBHOOK_URL is configured the existing n8n workflow is still called (with the
authenticated user id) and its reply is preferred, preserving the original chatbot behaviour.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from app.core.config import get_settings
from app.database.academic_repository import AcademicRepository, get_academic_repo
from app.models.schemas import QueryResponse, Source
from app.services.course_scope import courses_mentioned
from app.services.query_router import Intent, RoutedQuery

log = logging.getLogger(__name__)
TZ = ZoneInfo("Australia/Melbourne")


def _fmt_due(due_at: Optional[str]) -> str:
    if not due_at:
        return "no due date set in Canvas"
    try:
        dt = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ).strftime("%A %d %B %Y, %I:%M %p (Melbourne time)")
    except ValueError:
        return due_at


def _call_n8n(query: str, user_id: str, course_id: Optional[str]) -> Optional[str]:
    url = get_settings().n8n_webhook_url
    if not url:
        return None
    try:
        r = requests.post(url, json={"question": query, "user_id": user_id, "course_id": course_id}, timeout=20)
        if r.status_code >= 400:
            return None
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"reply": r.text}
        if isinstance(data, list) and data:
            data = data[0]
        reply = data.get("reply") or data.get("output") or data.get("answer") if isinstance(data, dict) else None
        return reply.strip() if isinstance(reply, str) and reply.strip() else None
    except (requests.RequestException, ValueError):
        log.warning("n8n webhook unavailable; answering from synced Canvas data")
        return None


def answer_structured(
    user_id: str, course_id: Optional[str], query: str, routed: RoutedQuery,
    repo: Optional[AcademicRepository] = None,
) -> QueryResponse:
    repo = repo or get_academic_repo()
    n8n_reply = _call_n8n(query, user_id, course_id)
    if n8n_reply:
        return QueryResponse(reply=n8n_reply, route=routed.route.value, intent=routed.intent.value, confidence=0.7,
                             notes=["Answered by the existing n8n workflow."])

    courses = {str(c["course_id"]): c for c in repo.list_courses(user_id)}
    course_name = lambda cid: (courses.get(str(cid)) or {}).get("course_name") or f"course {cid}"
    sources: list[Source] = []

    if routed.intent in (Intent.DEADLINE, Intent.ASSIGNMENT_LIST):
        canvas_course = course_id if course_id in courses else None
        assignments = repo.list_assignments(user_id, canvas_course)
        if not assignments:
            return QueryResponse(reply="I don't have any assignments synced from Canvas yet. Use “Sync Canvas” to fetch them.",
                                 route=routed.route.value, intent=routed.intent.value, confidence=0.3)
        scope = courses_mentioned(query, courses)
        if scope:
            assignments = [a for a in assignments if str(a.get("course_id")) in scope] or assignments
        now = datetime.now(timezone.utc).isoformat()
        upcoming = sorted((a for a in assignments if (a.get("due_at") or "") >= now), key=lambda a: a["due_at"])
        num = re.search(r"(\d+)\s*$", routed.assignment_ref or "")
        matches = assignments
        hidden_past = 0
        if routed.intent == Intent.DEADLINE:
            if num:
                n = num.group(1)
                matches = [a for a in assignments if re.search(
                    rf"\b(assignment|assessment|task|project|quiz|lab|test|exam|a)\s*#?\s*0?{n}\b",
                    (a.get("assignment_name") or "").lower())]
                # the one still to come is what's being asked about; older semesters' namesakes only if nothing is
                future = sorted((a for a in matches if (a.get("due_at") or "") >= now), key=lambda a: a["due_at"])
                past = sorted((a for a in matches if (a.get("due_at") or "") < now), key=lambda a: a.get("due_at") or "", reverse=True)
                matches, hidden_past = (future, len(past)) if future else (past, 0)
            elif upcoming:
                matches = upcoming[:1] if re.search(r"\b(next|upcoming|soonest)\b", query, re.I) else upcoming[:5]
            else:
                past = sorted((a for a in assignments if a.get("due_at")), key=lambda a: a["due_at"], reverse=True)
                where = f" for {', '.join(course_name(c) for c in scope)}" if scope else ""
                last = (f" The most recent deadline was {past[0].get('assignment_name')} ({course_name(past[0].get('course_id'))}),"
                        f" due {_fmt_due(past[0].get('due_at'))}." if past else "")
                return QueryResponse(reply=f"You have no upcoming deadlines{where} in Canvas.{last}",
                                     route=routed.route.value, intent=routed.intent.value, confidence=0.9)
        if not matches:
            names = ", ".join(a.get("assignment_name") or "?" for a in (upcoming or assignments)[:10])
            return QueryResponse(
                reply=f"I couldn't find “{routed.assignment_ref}” among your synced assignments"
                + (f" for {', '.join(course_name(c) for c in scope)}" if scope else "") + f". Upcoming: {names}",
                route=routed.route.value, intent=routed.intent.value, confidence=0.4,
            )
        if routed.intent == Intent.ASSIGNMENT_LIST:
            matches = upcoming[:10]
        lines = []
        for i, a in enumerate(matches[:10], 1):
            lines.append(f"• {a.get('assignment_name')} ({course_name(a.get('course_id'))}) — due {_fmt_due(a.get('due_at'))}"
                         + (f", worth {a['points_possible']:g} points" if a.get("points_possible") else "") + f" [C{i}]")
            sources.append(Source(id=f"C{i}", type="canvas", title=a.get("assignment_name") or "Assignment",
                                  course_id=str(a.get("course_id")), url=a.get("html_url")))
        reply = "\n".join(lines) if lines else "You have no upcoming assignments with due dates in Canvas."
        if hidden_past:
            reply += (f"\n\n({hidden_past} past assignment{'s' if hidden_past > 1 else ''} with the same name from earlier"
                      " semesters not shown. Pick a course to narrow it down.)")
        return QueryResponse(reply=reply, sources=sources, route=routed.route.value, intent=routed.intent.value, confidence=0.95)

    if routed.intent == Intent.COURSE_LIST:
        if not courses:
            return QueryResponse(reply="No courses synced from Canvas yet. Use “Sync Canvas” first.",
                                 route=routed.route.value, intent=routed.intent.value, confidence=0.3)
        lines = [f"• {c.get('course_code') or ''} {c.get('course_name')}".strip() for c in courses.values()]
        return QueryResponse(reply="Your Canvas courses:\n" + "\n".join(lines), route=routed.route.value,
                             intent=routed.intent.value, confidence=0.95)

    if routed.intent == Intent.TIMETABLE:
        rows = repo.list_timetable(user_id)
        if not rows:
            return QueryResponse(reply="You haven't saved your class times yet (Find Classmate → Save).",
                                 route=routed.route.value, intent=routed.intent.value, confidence=0.4)
        lines = [f"• {r.get('course_name')} ({'theory' if r.get('is_theory') else 'practical'}): "
                 f"{r.get('day_of_course')} {r.get('time_of_day')}, room {r.get('room_of_course')}" for r in rows]
        return QueryResponse(reply="Your saved timetable:\n" + "\n".join(lines), route=routed.route.value,
                             intent=routed.intent.value, confidence=0.9)

    if routed.intent == Intent.CLASSMATES:
        return QueryResponse(reply="Open “Find Classmate” in the sidebar to match with students in the same classes.",
                             route=routed.route.value, intent=routed.intent.value, confidence=0.6)

    return QueryResponse(
        reply="Grade data isn't synced from Canvas yet, so I can't answer grade questions reliably.",
        route=routed.route.value, intent=routed.intent.value, confidence=0.3,
    )
