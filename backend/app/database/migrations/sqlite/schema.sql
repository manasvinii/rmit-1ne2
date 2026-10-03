-- Local development / test schema. Mirrors migrations/postgres/*.sql plus the legacy
-- academic tables that live in Supabase in the hosted deployment.

CREATE TABLE IF NOT EXISTS "User" (
    user_id     TEXT PRIMARY KEY,
    full_name   TEXT,
    email       TEXT UNIQUE NOT NULL,
    api_token   TEXT,            -- Fernet-encrypted Canvas token ("enc:v1:...")
    password    TEXT             -- bcrypt hash
);

CREATE TABLE IF NOT EXISTS "Courses" (
    course_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    course_name TEXT,
    course_code TEXT,
    created_at  TEXT,
    start_at    TEXT,
    end_at      TEXT,
    email       TEXT,
    apply_assignment_group_weights INTEGER,
    PRIMARY KEY (user_id, course_id)
);

CREATE TABLE IF NOT EXISTS "Assignments" (
    assignment_id    TEXT NOT NULL,
    course_id        TEXT NOT NULL,
    user_id          TEXT NOT NULL,
    assignment_name  TEXT,
    description      TEXT,
    due_at           TEXT,
    created_at       TEXT,
    points_possible  REAL,
    submission_types TEXT,
    html_url         TEXT,
    PRIMARY KEY (user_id, assignment_id)
);

CREATE TABLE IF NOT EXISTS "Course_timetable" (
    user_id        TEXT NOT NULL,
    course_id      TEXT NOT NULL,
    day_of_course  TEXT,
    time_of_day    TEXT,
    room_of_course TEXT,
    course_name    TEXT,
    is_theory      INTEGER
);

CREATE TABLE IF NOT EXISTS lecture_resources (
    resource_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL,
    module_id TEXT, module_name TEXT, title TEXT NOT NULL, resource_type TEXT NOT NULL,
    mime_type TEXT, canvas_url TEXT, download_url TEXT, local_path TEXT,
    source_provider TEXT NOT NULL, week INTEGER, lecture_number INTEGER,
    is_external INTEGER NOT NULL DEFAULT 0, content_hash TEXT, source_updated_at TEXT,
    size_bytes INTEGER, status TEXT NOT NULL DEFAULT 'pending', error TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_resources_user_course ON lecture_resources (user_id, course_id);

CREATE TABLE IF NOT EXISTS lecture_segments (
    segment_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL,
    resource_id TEXT NOT NULL REFERENCES lecture_resources(resource_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, start_time REAL NOT NULL, end_time REAL NOT NULL, text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_resource ON lecture_segments (user_id, resource_id, seq);

CREATE TABLE IF NOT EXISTS content_chunks (
    chunk_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL,
    resource_id TEXT NOT NULL REFERENCES lecture_resources(resource_id) ON DELETE CASCADE,
    lecture_id TEXT NOT NULL, content_type TEXT NOT NULL, heading TEXT, module TEXT,
    week INTEGER, resource_title TEXT NOT NULL, text TEXT NOT NULL, page_number INTEGER,
    page_end INTEGER, start_time REAL, end_time REAL, source_url TEXT,
    metadata TEXT NOT NULL DEFAULT '{}', embedding BLOB,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chunks_scope ON content_chunks (user_id, course_id, week, content_type);

CREATE TABLE IF NOT EXISTS kg_nodes (
    node_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL,
    node_type TEXT NOT NULL, node_key TEXT NOT NULL, label TEXT NOT NULL, description TEXT,
    properties TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, course_id, node_type, node_key)
);
CREATE INDEX IF NOT EXISTS idx_nodes_scope ON kg_nodes (user_id, course_id, node_type);

CREATE TABLE IF NOT EXISTS kg_node_aliases (
    node_id TEXT NOT NULL REFERENCES kg_nodes(node_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL, course_id TEXT NOT NULL, alias TEXT NOT NULL, alias_norm TEXT NOT NULL,
    PRIMARY KEY (node_id, alias_norm)
);
CREATE INDEX IF NOT EXISTS idx_alias_lookup ON kg_node_aliases (user_id, course_id, alias_norm);

CREATE TABLE IF NOT EXISTS kg_edges (
    edge_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL,
    source_node_id TEXT NOT NULL REFERENCES kg_nodes(node_id) ON DELETE CASCADE,
    relation TEXT NOT NULL,
    target_node_id TEXT NOT NULL REFERENCES kg_nodes(node_id) ON DELETE CASCADE,
    confidence REAL NOT NULL, extraction_method TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, course_id, source_node_id, relation, target_node_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON kg_edges (user_id, course_id, source_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON kg_edges (user_id, course_id, target_node_id);

CREATE TABLE IF NOT EXISTS kg_edge_evidence (
    evidence_id TEXT PRIMARY KEY,
    edge_id TEXT NOT NULL REFERENCES kg_edges(edge_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    chunk_id TEXT REFERENCES content_chunks(chunk_id) ON DELETE CASCADE,
    resource_id TEXT, page_number INTEGER, start_time REAL, end_time REAL, quote TEXT,
    extraction_method TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_edge ON kg_edge_evidence (edge_id);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL, resource_id TEXT,
    status TEXT NOT NULL, stage TEXT, error TEXT, stats TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON ingestion_jobs (user_id, course_id, started_at);

-- Pupil teaching sessions: the student teaches an AI persona from a chosen slice of their material.
CREATE TABLE IF NOT EXISTS teach_sessions (
    session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL,
    persona TEXT NOT NULL, weeks TEXT NOT NULL DEFAULT '[]', resource_ids TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL DEFAULT '{}', summary TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, ended_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_teach_sessions_user ON teach_sessions (user_id, course_id, started_at);

CREATE TABLE IF NOT EXISTS teach_turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES teach_sessions(session_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL,
    via TEXT, at_seconds INTEGER NOT NULL DEFAULT 0, idea_id TEXT,
    assessment TEXT NOT NULL DEFAULT '{}', evidence TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_teach_turns_session ON teach_turns (user_id, session_id, seq);
