"""Subjects, weeks and materials for the Pupil UI, read from the student's own synced Canvas store.

Everything here is built from resources that were downloaded with the student's Canvas token and
ingested (lecture slides, lab notebooks, uploaded recordings). Nothing calls Canvas at request time.

A teaching scope is (student, course, set of weeks, set of resources). The material ticks in Setup
become the resource set, and both vector retrieval and graph lookups are filtered by it.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

from app.core.auth import allowed_course_ids
from app.core.config import get_settings
from app.database.academic_repository import get_academic_repo
from app.database.graph_repository import GraphRepository
from app.database.resource_repository import ResourceRepository
from app.database.vector_repository import ChunkFilter, VectorRepository
from app.models.graph_models import NodeType
from app.models.resource_models import IngestionStatus, LectureResource, ResourceType

DEFAULT_TOTAL_WEEKS = 12
MAX_WEEK = 20
MAX_CONTENT_CHARS = 400_000

KIND_ORDER = ("video", "slides", "reading", "file")
_PLURALS = {"video": ("lectorial", "lectorials"), "slides": ("slide deck", "slide decks"),
            "reading": ("reading", "readings"), "file": ("tutorial sheet", "tutorial sheets")}


class ScopeError(ValueError):
    pass


def parse_weeks(week: Optional[int] = None, mode: str = "single", weeks: Optional[str | Iterable[int]] = None) -> list[int]:
    """`weeks=1,3,5` (any combination) wins; otherwise `week` alone or, in range mode, weeks 1..week."""
    if weeks:
        raw = weeks.split(",") if isinstance(weeks, str) else list(weeks)
        try:
            out = sorted({int(str(w).strip()) for w in raw if str(w).strip()})
        except ValueError as e:
            raise ScopeError("weeks must be a comma-separated list of week numbers") from e
    elif week:
        out = list(range(1, week + 1)) if mode == "range" else [int(week)]
    else:
        raise ScopeError("Choose at least one week")
    if not out or any(w < 1 or w > MAX_WEEK for w in out):
        raise ScopeError(f"Weeks must be between 1 and {MAX_WEEK}")
    return out


def weeks_label(weeks: Sequence[int]) -> str:
    ws = sorted(weeks)
    if len(ws) == 1:
        return f"Week {ws[0]}"
    if ws == list(range(ws[0], ws[-1] + 1)):
        return f"Weeks {ws[0]}–{ws[-1]}"
    return "Weeks " + ", ".join(str(w) for w in ws)


def material_kind(res: LectureResource) -> str:
    """Same four kinds the UI uses: video | slides | reading | file (tutorial/lab sheets)."""
    if res.resource_type in (ResourceType.VIDEO, ResourceType.TRANSCRIPT):
        return "video"
    if res.metadata.get("role") == "lab":
        return "file"
    if res.resource_type in (ResourceType.PDF, ResourceType.SLIDES):
        return "slides" if res.metadata.get("deck_title") or res.lecture_number or res.metadata.get("role") in (None, "lecture") else "reading"
    if res.resource_type == ResourceType.PAGE:
        return "reading"
    return "file"


def _course_name(name: str) -> str:
    """'Computational Machine Learning (2650)' -> 'Computational Machine Learning'."""
    name = re.sub(r"\s*\(\d{3,}\)\s*$", "", name or "")
    name = re.sub(r"^[A-Z]{3,4}\d{4}\s*[-–:]?\s*", "", name)
    return name.strip()


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _mmss(seconds: Optional[float]) -> str:
    s = int(seconds or 0)
    return f"{s // 60}:{s % 60:02d}"


@dataclass
class Scope:
    user_id: str
    course_id: str
    weeks: list[int]
    resource_ids: list[str]
    materials: list[dict] = field(default_factory=list)  # rows as shown in Setup, with `included`

    @property
    def label(self) -> str:
        return weeks_label(self.weeks)


class StudyCatalog:
    def __init__(self, resources: Optional[ResourceRepository] = None, vectors: Optional[VectorRepository] = None,
                 graph: Optional[GraphRepository] = None, now=None):
        self.resources = resources or ResourceRepository()
        self.vectors = vectors or VectorRepository()
        self.graph = graph or GraphRepository()
        self._now = now or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------ authorisation
    def authorise(self, user_id: str, course_id: str) -> str:
        if str(course_id) not in allowed_course_ids(user_id):
            raise PermissionError("You are not enrolled in that course")
        return str(course_id)

    def usable(self, user_id: str, course_id: str) -> list[LectureResource]:
        """Ingested, owned resources of a course (only these can teach the AI student)."""
        return [r for r in self.resources.list(user_id, course_id)
                if r.status == IngestionStatus.COMPLETED and r.week is not None and not r.is_external]

    # ------------------------------------------------------------------ weeks / topics
    def topics(self, user_id: str, course_id: str) -> dict[int, str]:
        def tidy(title: str) -> str:  # deck titles cut at a line break: "Other Learning Paradigms and"
            return re.sub(r"(\s+(and|or|of|the|to|for|with|&|-|–))+\s*$", "", (title or "").strip(), flags=re.I)

        topics: dict[int, str] = {}
        for n in self.graph.list_nodes(user_id, [course_id], [NodeType.LECTURE.value]):
            w, title = n.properties.get("week"), tidy(n.properties.get("title") or "")
            if w and title:
                topics[int(w)] = title
        for r in self.usable(user_id, course_id):
            deck = tidy(r.metadata.get("deck_title") or "")
            if r.week and r.week not in topics and deck:
                topics[r.week] = deck
            elif r.week and r.week not in topics and material_kind(r) == "slides":
                topics[r.week] = re.sub(r"^Lecture\s*\d+\s*", "", r.title).strip() or f"Week {r.week}"
        return topics

    def current_week(self, course: Optional[dict], total: int) -> int:
        override = os.getenv("CURRENT_WEEK", "").strip()
        if override.isdigit():
            return max(1, min(total, int(override)))
        start = _parse_ts((course or {}).get("start_at"))
        if start:
            return max(1, min(total, (self._now() - start).days // 7 + 1))
        return total

    def subject(self, user_id: str, course_id: str, course: Optional[dict], progress: Optional[dict[int, str]] = None) -> Optional[dict]:
        usable = self.usable(user_id, course_id)
        if not usable:
            return None
        by_week: dict[int, list[LectureResource]] = defaultdict(list)
        for r in usable:
            by_week[r.week].append(r)
        total = max([DEFAULT_TOTAL_WEEKS, *by_week])
        current = self.current_week(course, total)
        teach_week = max((w for w in by_week if w <= current), default=min(by_week))
        topics = self.topics(user_id, course_id)
        progress = progress or {}
        strip = "".join(progress.get(n) or ("N" if n <= current and n in by_week else "U") for n in range(1, total + 1))
        latest_untaught = teach_week not in progress
        return {
            "id": str(course_id),
            "code": (course or {}).get("course_code") or "",
            "name": _course_name((course or {}).get("course_name") or "") or f"Course {course_id}",
            "badge": ({"label": f"Week {teach_week} new", "tone": "new"} if latest_untaught
                      else {"label": "On track", "tone": "ok"}),
            "materialsSummary": summary_of(material_kind(r) for r in by_week[teach_week]),
            "cta": f"Teach Week {teach_week}" if latest_untaught else f"Revise Weeks 1–{teach_week}",
            "progress": strip,
            "topics": [topics.get(n) or f"Week {n}" for n in range(1, total + 1)],
            "currentWeek": teach_week,
            "totalWeeks": total,
            "weeksWithMaterial": sorted(by_week),
            "term": None,
            "canvasUrl": f"{get_settings().canvas_base_url}/courses/{course_id}",
        }

    def subjects(self, user_id: str, progress_by_course: Optional[dict[str, dict[int, str]]] = None) -> dict:
        courses = {str(c["course_id"]): c for c in get_academic_repo().list_courses(user_id)}
        ids = sorted(set(allowed_course_ids(user_id)))
        subjects, skipped = [], []
        for cid in ids:
            s = self.subject(user_id, cid, courses.get(cid), (progress_by_course or {}).get(cid))
            if s:
                subjects.append(s)
            elif cid in courses:
                skipped.append(courses[cid].get("course_name"))
        return {
            "currentWeek": max([s["currentWeek"] for s in subjects], default=1),
            "totalWeeks": max([s["totalWeeks"] for s in subjects], default=DEFAULT_TOTAL_WEEKS),
            "subjects": subjects,
            "skippedCourses": skipped,  # enrolled, but no lecture material synced yet
        }

    def weeks_overview(self, user_id: str, course_id: str) -> list[dict]:
        course = get_academic_repo().get_course(user_id, course_id)
        usable = self.usable(user_id, course_id)
        by_week: dict[int, list[LectureResource]] = defaultdict(list)
        for r in usable:
            by_week[r.week].append(r)
        total = max([DEFAULT_TOTAL_WEEKS, *by_week])
        current = self.current_week(course, total)
        topics = self.topics(user_id, course_id)
        return [{"week": n, "topic": topics.get(n) or f"Week {n}", "released": n <= current,
                 "modules": sorted({r.module_name for r in by_week[n] if r.module_name}),
                 "itemCount": len(by_week[n])} for n in sorted(by_week)]

    # ------------------------------------------------------------------ materials
    def _chunk_stats(self, user_id: str, course_id: str, weeks: Sequence[int]) -> dict[str, dict]:
        stats: dict[str, dict] = defaultdict(lambda: {"chunks": 0, "max_page": 0, "max_time": 0.0})
        for c in self.vectors.list_chunks(ChunkFilter(user_id, [course_id], weeks=list(weeks))):
            s = stats[c.resource_id]
            s["chunks"] += 1
            s["max_page"] = max(s["max_page"], c.page_end or c.page_number or 0)
            s["max_time"] = max(s["max_time"], c.end_time or 0.0)
        return stats

    def _sub(self, r: LectureResource, kind: str, st: dict) -> str:
        if kind == "video":
            secs = r.metadata.get("duration_seconds") or st.get("max_time") or 0
            label = "Recording" if r.source_provider.value == "canvas" else "Uploaded recording"
            return f"{label} · {round(secs / 60)} min" if secs else label
        if r.metadata.get("role") == "lab":
            return f"Lab notebook · {r.metadata.get('section_count') or st.get('chunks', 0)} sections"
        pages = r.metadata.get("page_count") or st.get("max_page")
        return f"PDF · {pages} slides" if kind == "slides" and pages else ("PDF" if pages else "File")

    def _row(self, user_id: str, r: LectureResource, st: dict) -> dict:
        from app.api.resources import signed_resource_url

        kind = material_kind(r)
        return {
            "id": r.resource_id, "kind": kind, "title": r.title, "sub": self._sub(r, kind, st),
            "week": r.week, "off": kind == "file",  # tutorial/lab sheets start unticked, like the mock
            "source": {"type": "video" if kind == "video" else "file",
                       "url": signed_resource_url(user_id, r.resource_id, None, None),
                       "provider": r.source_provider.value},
        }

    def materials(self, user_id: str, course_id: str, weeks: Sequence[int]) -> list[dict]:
        """One row per resource for a single week; for several weeks, one summary row per kind
        (`items` lists the resources it stands for), as the Setup screen expects."""
        weeks = sorted(set(weeks))
        res = sorted((r for r in self.usable(user_id, course_id) if r.week in weeks),
                     key=lambda r: (KIND_ORDER.index(material_kind(r)), r.week, r.title))
        stats = self._chunk_stats(user_id, course_id, weeks)
        rows = [self._row(user_id, r, stats.get(r.resource_id, {})) for r in res]
        if len(weeks) == 1:
            return rows
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            groups[row["kind"]].append(row)
        out = []
        for kind in KIND_ORDER:
            items = groups.get(kind)
            if not items:
                continue
            one, many = _PLURALS[kind]
            covered = sorted({i["week"] for i in items})
            out.append({
                "id": f"group-{kind}", "kind": kind,
                "title": f"{len(items)} {one if len(items) == 1 else many}",
                "sub": weeks_label(covered) + ("" if len(covered) == len(weeks) else f" (of {weeks_label(weeks)})"),
                "off": kind == "file", "items": [i["id"] for i in items],
                "children": [{k: i[k] for k in ("id", "title", "sub", "week", "source")} for i in items],
            })
        return out

    def resolve_scope(self, user_id: str, course_id: str, weeks: Sequence[int],
                      exclude: Iterable[str] = (), include: Iterable[str] = ()) -> Scope:
        """Turn Setup's ticks into the exact resource set the AI student may learn from.

        exclude: ids the student unticked (resource ids, or group-<kind> rows in multi-week mode)
        include: ids that are off by default (tutorial/lab sheets) but were ticked
        """
        course_id = self.authorise(user_id, course_id)
        weeks = sorted(set(weeks))
        ex, inc = set(exclude), set(include)
        rows = self.materials(user_id, course_id, weeks)
        allowed: list[str] = []
        shown = []
        for row in rows:
            row_on = (row["id"] in inc) if row["off"] else (row["id"] not in ex)
            members = row.get("items") or [row["id"]]
            on_members = [m for m in members if (row_on and m not in ex) or m in inc]
            allowed.extend(on_members)
            shown.append({"id": row["id"], "kind": row["kind"], "title": row["title"], "included": bool(on_members)})
        allowed = list(dict.fromkeys(allowed))
        if not allowed:
            raise ScopeError("Tick at least one material for the AI student to learn from")
        return Scope(user_id, course_id, weeks, allowed, shown)

    # ------------------------------------------------------------------ content / downloads
    def content(self, scope: Scope) -> dict:
        chunks = self.vectors.list_chunks(ChunkFilter(scope.user_id, [scope.course_id], weeks=scope.weeks,
                                                      resource_ids=scope.resource_ids))
        parts, used, total = [], defaultdict(int), 0
        topics = self.topics(scope.user_id, scope.course_id)
        for c in chunks:
            loc = (f"{_mmss(c.start_time)}" if c.start_time is not None
                   else f"{'cell' if c.content_type.value == 'notebook' else 'p.'}{c.page_number}")
            block = f"### Week {c.week} · {topics.get(c.week, '')} · {c.resource_title} ({loc})\n{c.heading or ''}\n{c.text}"
            if total + len(block) > MAX_CONTENT_CHARS:
                break
            parts.append(block)
            total += len(block)
            used[(c.resource_id, c.resource_title)] += len(c.text)
        return {
            "courseId": scope.course_id, "weeks": scope.weeks, "week": max(scope.weeks),
            "mode": "single" if len(scope.weeks) == 1 else "multi",
            "topic": topics.get(scope.weeks[0]) if len(scope.weeks) == 1 else scope.label,
            "materials": [{"id": rid, "title": t, "chars": n} for (rid, t), n in used.items()],
            "text": "\n\n".join(parts),
        }

    def zip_bytes(self, scope: Scope) -> tuple[str, bytes]:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for rid in scope.resource_ids:
                r = self.resources.get(scope.user_id, rid)
                if r and r.local_path and Path(r.local_path).is_file():
                    z.write(r.local_path, f"week_{r.week:02d}/{Path(r.local_path).name}")
        slug = "-".join(str(w) for w in scope.weeks) if len(scope.weeks) <= 4 else f"{scope.weeks[0]}-{scope.weeks[-1]}"
        return f"course-{scope.course_id}-weeks-{slug}.zip", buf.getvalue()


def summary_of(kinds: Iterable[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for k in kinds:
        counts[k] += 1
    parts = [f"{counts[k]} {_PLURALS[k][0] if counts[k] == 1 else _PLURALS[k][1]}" for k in KIND_ORDER if counts.get(k)]
    return " · ".join(parts) or "No materials synced yet"
