"""Detect which of the student's courses a question refers to, so similar courses don't mix."""

from __future__ import annotations

import re

_STOP = {"and", "of", "for", "the", "with", "in", "to", "a", "an", "part", "data", "science", "introduction"}


def _name_words(course: dict) -> list[str]:
    name = re.sub(r"\(.*?\)", "", course.get("course_name") or "").lower()
    return [w for w in re.findall(r"[a-z]+", name) if w not in _STOP and len(w) > 2]


def strip_course_mentions(query: str, courses: dict[str, dict], ids: set[str]) -> str:
    """Remove the named courses' codes / name words so they aren't mistaken for lecture concepts
    ("Computational Machine Learning" must not link the concept "Machine Learning")."""
    out = query
    for cid in ids:
        c = courses.get(cid) or {}
        drop = [w for w in [(c.get("course_code") or "").lower(), *_name_words(c)] if w]
        if drop:
            out = re.sub(r"\b(" + "|".join(map(re.escape, drop)) + r")\b", " ", out, flags=re.I)
    out = re.sub(r"\s+", " ", out).strip(" ,")
    return out if re.search(r"[A-Za-z]{3}", out) else query


def courses_mentioned(query: str, courses: dict[str, dict]) -> set[str]:
    """Course ids referenced by code ('COSC2793') or by the distinctive words of their name."""
    q = query.lower()
    q_words = set(re.findall(r"[a-z0-9]+", q))
    hits: set[str] = set()
    by_name: dict[str, set[str]] = {}
    for cid, c in courses.items():
        code = (c.get("course_code") or "").lower()
        if code and re.fullmatch(r"[a-z]{4}\d{4}", code) and code in q:
            hits.add(cid)
            continue
        words = _name_words(c)
        shared = {w for w in words if w in q_words}
        if words and len(shared) >= min(2, len(words)):
            by_name[cid] = shared
    # "Computational Machine Learning" names that course, not also the plain "Machine Learning" one
    hits |= {cid for cid, s in by_name.items() if not any(s < other for other in by_name.values())}
    return hits
