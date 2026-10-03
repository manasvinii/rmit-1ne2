"""Access to the existing academic tables: User, Courses, Assignments, Course_timetable.

Two interchangeable backends:
- SupabaseAcademicRepository: the original Supabase REST tables (hosted deployment).
- SqlAcademicRepository: the same tables in the local SQL database (dev/tests).
Every method that returns student data takes the authenticated user_id explicitly.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from app.core.config import get_settings
from app.database.db import Database, get_db

log = logging.getLogger(__name__)

COURSE_FIELDS = (
    "course_id", "user_id", "course_name", "course_code", "created_at", "start_at", "end_at",
    "email", "apply_assignment_group_weights",
)
ASSIGNMENT_FIELDS = (
    "assignment_id", "course_id", "user_id", "assignment_name", "description", "due_at",
    "created_at", "points_possible", "submission_types", "html_url",
)
TIMETABLE_FIELDS = (
    "user_id", "course_id", "day_of_course", "time_of_day", "room_of_course", "course_name",
    "is_theory",
)


class AcademicRepository(Protocol):
    def get_user_by_email(self, email: str) -> Optional[dict]: ...
    def get_user(self, user_id: str) -> Optional[dict]: ...
    def create_user(self, row: dict) -> dict: ...
    def update_user(self, user_id: str, fields: dict) -> None: ...
    def list_courses(self, user_id: str) -> list[dict]: ...
    def get_course(self, user_id: str, course_id: str) -> Optional[dict]: ...
    def upsert_courses(self, rows: list[dict]) -> int: ...
    def list_assignments(self, user_id: str, course_id: Optional[str] = None) -> list[dict]: ...
    def upsert_assignments(self, rows: list[dict]) -> int: ...
    def timetable_entry_exists(self, user_id: str, course_id: str) -> bool: ...
    def insert_timetable(self, row: dict) -> None: ...
    def list_timetable(self, user_id: str) -> list[dict]: ...
    def find_same_slot(self, user_id: str, slot: dict) -> list[dict]: ...


def _legacy_id(value: str) -> Any:
    """The prototype's Supabase tables use integer user ids."""
    return int(value) if str(value).isdigit() else value


class SupabaseAcademicRepository:
    def __init__(self):
        from supabase import create_client

        s = get_settings()
        self.client = create_client(s.supabase_url, s.supabase_key)

    def _t(self, name: str):
        return self.client.table(name)

    def get_user_by_email(self, email: str) -> Optional[dict]:
        res = self._t("User").select("*").eq("email", email).execute()
        return res.data[0] if res.data else None

    def get_user(self, user_id: str) -> Optional[dict]:
        res = self._t("User").select("*").eq("user_id", _legacy_id(user_id)).execute()
        return res.data[0] if res.data else None

    def create_user(self, row: dict) -> dict:
        row = {**row, "user_id": _legacy_id(row["user_id"])}
        return self._t("User").insert(row).execute().data[0]

    def update_user(self, user_id: str, fields: dict) -> None:
        self._t("User").update(fields).eq("user_id", _legacy_id(user_id)).execute()

    def list_courses(self, user_id: str) -> list[dict]:
        return self._t("Courses").select("*").eq("user_id", _legacy_id(user_id)).execute().data or []

    def get_course(self, user_id: str, course_id: str) -> Optional[dict]:
        res = (
            self._t("Courses").select("*").eq("user_id", _legacy_id(user_id))
            .eq("course_id", _legacy_id(course_id)).execute()
        )
        return res.data[0] if res.data else None

    def upsert_courses(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        rows = [{**r, "user_id": _legacy_id(r["user_id"])} for r in rows]
        res = self._t("Courses").upsert(rows, on_conflict="user_id,course_id").execute()
        return len(res.data or [])

    def list_assignments(self, user_id: str, course_id: Optional[str] = None) -> list[dict]:
        q = self._t("Assignments").select("*").eq("user_id", _legacy_id(user_id))
        if course_id is not None:
            q = q.eq("course_id", _legacy_id(course_id))
        return q.execute().data or []

    def upsert_assignments(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        rows = [{**r, "user_id": _legacy_id(r["user_id"])} for r in rows]
        res = self._t("Assignments").upsert(rows, on_conflict="user_id,assignment_id").execute()
        return len(res.data or [])

    def timetable_entry_exists(self, user_id: str, course_id: str) -> bool:
        res = (
            self._t("Course_timetable").select("course_id").eq("user_id", _legacy_id(user_id))
            .eq("course_id", _legacy_id(course_id)).execute()
        )
        return bool(res.data)

    def insert_timetable(self, row: dict) -> None:
        self._t("Course_timetable").insert({**row, "user_id": _legacy_id(row["user_id"])}).execute()

    def list_timetable(self, user_id: str) -> list[dict]:
        return (
            self._t("Course_timetable").select("*").eq("user_id", _legacy_id(user_id)).execute().data
            or []
        )

    def find_same_slot(self, user_id: str, slot: dict) -> list[dict]:
        return (
            self._t("Course_timetable").select("*")
            .eq("course_id", slot["course_id"]).eq("day_of_course", slot["day_of_course"])
            .eq("time_of_day", slot["time_of_day"]).eq("room_of_course", slot["room_of_course"])
            .eq("is_theory", slot["is_theory"]).neq("user_id", _legacy_id(user_id))
            .execute().data
            or []
        )


class SqlAcademicRepository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    def get_user_by_email(self, email: str) -> Optional[dict]:
        return self.db.fetchone('SELECT * FROM "User" WHERE email = ?', (email,))

    def get_user(self, user_id: str) -> Optional[dict]:
        return self.db.fetchone('SELECT * FROM "User" WHERE user_id = ?', (str(user_id),))

    def create_user(self, row: dict) -> dict:
        cols = ["user_id", "full_name", "email", "api_token", "password"]
        self.db.execute(
            f'INSERT INTO "User" ({", ".join(cols)}) VALUES ({", ".join("?" * len(cols))})',
            [str(row.get(c)) if c == "user_id" else row.get(c) for c in cols],
        )
        return self.get_user(row["user_id"])  # type: ignore[return-value]

    def update_user(self, user_id: str, fields: dict) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f'UPDATE "User" SET {sets} WHERE user_id = ?', [*fields.values(), str(user_id)])

    def list_courses(self, user_id: str) -> list[dict]:
        return self.db.fetchall('SELECT * FROM "Courses" WHERE user_id = ?', (str(user_id),))

    def get_course(self, user_id: str, course_id: str) -> Optional[dict]:
        return self.db.fetchone(
            'SELECT * FROM "Courses" WHERE user_id = ? AND course_id = ?', (str(user_id), str(course_id))
        )

    def _upsert(self, table: str, fields: tuple, keys: tuple, rows: list[dict]) -> int:
        if not rows:
            return 0
        updates = ", ".join(f"{f} = excluded.{f}" for f in fields if f not in keys)
        sql = (
            f'INSERT INTO "{table}" ({", ".join(fields)}) VALUES ({", ".join("?" * len(fields))}) '
            f'ON CONFLICT ({", ".join(keys)}) DO UPDATE SET {updates}'
        )

        def val(r, f):
            v = r.get(f)
            if f in ("user_id", "course_id", "assignment_id") and v is not None:
                return str(v)
            if isinstance(v, (list, dict)):
                import json

                return json.dumps(v)
            return v

        self.db.executemany(sql, [[val(r, f) for f in fields] for r in rows])
        return len(rows)

    def upsert_courses(self, rows: list[dict]) -> int:
        rows = [{**r, "email": r.get("email") if isinstance(r.get("email"), str) else None} for r in rows]
        return self._upsert("Courses", COURSE_FIELDS, ("user_id", "course_id"), rows)

    def list_assignments(self, user_id: str, course_id: Optional[str] = None) -> list[dict]:
        if course_id is None:
            return self.db.fetchall('SELECT * FROM "Assignments" WHERE user_id = ?', (str(user_id),))
        return self.db.fetchall(
            'SELECT * FROM "Assignments" WHERE user_id = ? AND course_id = ?',
            (str(user_id), str(course_id)),
        )

    def upsert_assignments(self, rows: list[dict]) -> int:
        return self._upsert("Assignments", ASSIGNMENT_FIELDS, ("user_id", "assignment_id"), rows)

    def timetable_entry_exists(self, user_id: str, course_id: str) -> bool:
        return bool(
            self.db.fetchone(
                'SELECT 1 AS x FROM "Course_timetable" WHERE user_id = ? AND course_id = ?',
                (str(user_id), str(course_id)),
            )
        )

    def insert_timetable(self, row: dict) -> None:
        self.db.execute(
            f'INSERT INTO "Course_timetable" ({", ".join(TIMETABLE_FIELDS)}) '
            f'VALUES ({", ".join("?" * len(TIMETABLE_FIELDS))})',
            [str(row[f]) if f in ("user_id", "course_id") else row.get(f) for f in TIMETABLE_FIELDS],
        )

    def list_timetable(self, user_id: str) -> list[dict]:
        rows = self.db.fetchall('SELECT * FROM "Course_timetable" WHERE user_id = ?', (str(user_id),))
        return [{**r, "is_theory": bool(r["is_theory"])} for r in rows]

    def find_same_slot(self, user_id: str, slot: dict) -> list[dict]:
        rows = self.db.fetchall(
            'SELECT * FROM "Course_timetable" WHERE course_id = ? AND day_of_course = ? '
            "AND time_of_day = ? AND room_of_course = ? AND is_theory = ? AND user_id != ?",
            (
                str(slot["course_id"]), slot["day_of_course"], slot["time_of_day"],
                slot["room_of_course"], int(bool(slot["is_theory"])), str(user_id),
            ),
        )
        return [{**r, "is_theory": bool(r["is_theory"])} for r in rows]


_repo: Optional[AcademicRepository] = None


def get_academic_repo() -> AcademicRepository:
    global _repo
    if _repo is None:
        _repo = SupabaseAcademicRepository() if get_settings().use_supabase_rest else SqlAcademicRepository()
    return _repo


def set_academic_repo(repo: Optional[AcademicRepository]) -> None:
    global _repo
    _repo = repo
