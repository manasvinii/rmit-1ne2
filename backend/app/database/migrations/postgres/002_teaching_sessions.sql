-- Pupil teaching sessions: the student teaches an AI persona from a chosen slice of their material.
CREATE TABLE IF NOT EXISTS teach_sessions (
    session_id    TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    course_id     TEXT NOT NULL,
    persona       TEXT NOT NULL,
    weeks         JSONB NOT NULL DEFAULT '[]'::jsonb,
    resource_ids  JSONB NOT NULL DEFAULT '[]'::jsonb,
    state         JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary       JSONB,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_teach_sessions_user ON teach_sessions (user_id, course_id, started_at);

CREATE TABLE IF NOT EXISTS teach_turns (
    turn_id     TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES teach_sessions(session_id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    role        TEXT NOT NULL,
    text        TEXT NOT NULL,
    via         TEXT,
    at_seconds  INTEGER NOT NULL DEFAULT 0,
    idea_id     TEXT,
    assessment  JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence    JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_teach_turns_session ON teach_turns (user_id, session_id, seq);

ALTER TABLE teach_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE teach_turns    ENABLE ROW LEVEL SECURITY;
