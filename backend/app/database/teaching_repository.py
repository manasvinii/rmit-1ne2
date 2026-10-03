"""Teaching sessions and their turns. Every read and write is scoped to the owning student."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.database.db import Database, get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TeachingRepository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    def _session(self, r: dict) -> dict:
        return {
            "session_id": r["session_id"], "user_id": r["user_id"], "course_id": r["course_id"],
            "persona": r["persona"], "weeks": self.db.load_json(r["weeks"]) or [],
            "resource_ids": self.db.load_json(r["resource_ids"]) or [],
            "state": self.db.load_json(r["state"]), "summary": self.db.load_json(r["summary"]) if r["summary"] else None,
            "started_at": str(r["started_at"]), "ended_at": str(r["ended_at"]) if r["ended_at"] else None,
        }

    def create(self, user_id: str, course_id: str, persona: str, weeks: list[int],
               resource_ids: list[str], state: dict) -> dict:
        sid = "ts_" + uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO teach_sessions (session_id, user_id, course_id, persona, weeks, resource_ids, state, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, str(user_id), str(course_id), persona, self.db.json(weeks), self.db.json(resource_ids),
             self.db.json(state), _now()),
        )
        return self.get(user_id, sid)  # type: ignore[return-value]

    def get(self, user_id: str, session_id: str) -> Optional[dict]:
        r = self.db.fetchone("SELECT * FROM teach_sessions WHERE user_id = ? AND session_id = ?",
                             (str(user_id), session_id))
        return self._session(r) if r else None

    def list(self, user_id: str, course_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        sql, params = "SELECT * FROM teach_sessions WHERE user_id = ?", [str(user_id)]
        if course_id is not None:
            sql += " AND course_id = ?"
            params.append(str(course_id))
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        return [self._session(r) for r in self.db.fetchall(sql, params)]

    def save_state(self, user_id: str, session_id: str, state: dict) -> None:
        self.db.execute("UPDATE teach_sessions SET state = ? WHERE user_id = ? AND session_id = ?",
                        (self.db.json(state), str(user_id), session_id))

    def finish(self, user_id: str, session_id: str, summary: dict) -> None:
        self.db.execute(
            "UPDATE teach_sessions SET summary = ?, ended_at = COALESCE(ended_at, ?) WHERE user_id = ? AND session_id = ?",
            (self.db.json(summary), _now(), str(user_id), session_id),
        )

    def add_turn(self, user_id: str, session_id: str, role: str, text: str, *, via: Optional[str] = None,
                 at_seconds: int = 0, idea_id: Optional[str] = None, assessment: Optional[dict] = None,
                 evidence: Optional[list[dict[str, Any]]] = None) -> dict:
        row = self.db.fetchone("SELECT COALESCE(MAX(seq), 0) AS n FROM teach_turns WHERE user_id = ? AND session_id = ?",
                               (str(user_id), session_id))
        seq = int((row or {}).get("n") or 0) + 1
        turn = {"turn_id": "tt_" + uuid.uuid4().hex, "seq": seq, "role": role, "text": text, "via": via,
                "at_seconds": int(at_seconds), "idea_id": idea_id, "assessment": assessment or {},
                "evidence": evidence or []}
        self.db.execute(
            "INSERT INTO teach_turns (turn_id, session_id, user_id, seq, role, text, via, at_seconds, idea_id, "
            "assessment, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (turn["turn_id"], session_id, str(user_id), seq, role, text, via, turn["at_seconds"], idea_id,
             self.db.json(turn["assessment"]), self.db.json(turn["evidence"])),
        )
        return turn

    def turns(self, user_id: str, session_id: str) -> list[dict]:
        rows = self.db.fetchall("SELECT * FROM teach_turns WHERE user_id = ? AND session_id = ? ORDER BY seq",
                                (str(user_id), session_id))
        return [{"turn_id": r["turn_id"], "seq": r["seq"], "role": r["role"], "text": r["text"], "via": r["via"],
                 "at_seconds": r["at_seconds"], "idea_id": r["idea_id"],
                 "assessment": self.db.load_json(r["assessment"]), "evidence": self.db.load_json(r["evidence"]) or []}
                for r in rows]
