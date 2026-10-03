-- RMIT 1NE: lecture content, vector index and evidence-grounded knowledge graph (Supabase / Postgres)
-- Idempotent. Requires the pgvector extension (Supabase: Database -> Extensions -> vector).
-- The vector dimension must match EMBEDDING_DIM (default 384 = BAAI/bge-small-en-v1.5).
-- Every row is owned by user_id; all application queries filter on it.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS lecture_resources (
    resource_id        TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL,
    course_id          TEXT NOT NULL,
    module_id          TEXT,
    module_name        TEXT,
    title              TEXT NOT NULL,
    resource_type      TEXT NOT NULL,
    mime_type          TEXT,
    canvas_url         TEXT,
    download_url       TEXT,
    local_path         TEXT,
    source_provider    TEXT NOT NULL,
    week               INTEGER,
    lecture_number     INTEGER,
    is_external        BOOLEAN NOT NULL DEFAULT FALSE,
    content_hash       TEXT,
    source_updated_at  TEXT,
    size_bytes         BIGINT,
    status             TEXT NOT NULL DEFAULT 'pending',
    error              TEXT,
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_resources_user_course ON lecture_resources (user_id, course_id);

CREATE TABLE IF NOT EXISTS lecture_segments (
    segment_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    course_id    TEXT NOT NULL,
    resource_id  TEXT NOT NULL REFERENCES lecture_resources(resource_id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    start_time   DOUBLE PRECISION NOT NULL,
    end_time     DOUBLE PRECISION NOT NULL,
    text         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_resource ON lecture_segments (user_id, resource_id, seq);

CREATE TABLE IF NOT EXISTS content_chunks (
    chunk_id        TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    course_id       TEXT NOT NULL,
    resource_id     TEXT NOT NULL REFERENCES lecture_resources(resource_id) ON DELETE CASCADE,
    lecture_id      TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    heading         TEXT,
    module          TEXT,
    week            INTEGER,
    resource_title  TEXT NOT NULL,
    text            TEXT NOT NULL,
    page_number     INTEGER,
    page_end        INTEGER,
    start_time      DOUBLE PRECISION,
    end_time        DOUBLE PRECISION,
    source_url      TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding       vector(384),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_scope ON content_chunks (user_id, course_id, week, content_type);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON content_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS kg_nodes (
    node_id      TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    course_id    TEXT NOT NULL,
    node_type    TEXT NOT NULL,      -- Course | Lecture | Resource | Concept | Assignment | ...
    node_key     TEXT NOT NULL,      -- normalized key (canonical concept key, lecture key, ...)
    label        TEXT NOT NULL,
    description  TEXT,
    properties   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, course_id, node_type, node_key)
);
CREATE INDEX IF NOT EXISTS idx_nodes_scope ON kg_nodes (user_id, course_id, node_type);

CREATE TABLE IF NOT EXISTS kg_node_aliases (
    node_id     TEXT NOT NULL REFERENCES kg_nodes(node_id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL,
    course_id   TEXT NOT NULL,
    alias       TEXT NOT NULL,
    alias_norm  TEXT NOT NULL,
    PRIMARY KEY (node_id, alias_norm)
);
CREATE INDEX IF NOT EXISTS idx_alias_lookup ON kg_node_aliases (user_id, course_id, alias_norm);

CREATE TABLE IF NOT EXISTS kg_edges (
    edge_id            TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL,
    course_id          TEXT NOT NULL,
    source_node_id     TEXT NOT NULL REFERENCES kg_nodes(node_id) ON DELETE CASCADE,
    relation           TEXT NOT NULL,
    target_node_id     TEXT NOT NULL REFERENCES kg_nodes(node_id) ON DELETE CASCADE,
    confidence         DOUBLE PRECISION NOT NULL,
    extraction_method  TEXT NOT NULL,
    properties         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, course_id, source_node_id, relation, target_node_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON kg_edges (user_id, course_id, source_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON kg_edges (user_id, course_id, target_node_id);

CREATE TABLE IF NOT EXISTS kg_edge_evidence (
    evidence_id        TEXT PRIMARY KEY,
    edge_id            TEXT NOT NULL REFERENCES kg_edges(edge_id) ON DELETE CASCADE,
    user_id            TEXT NOT NULL,
    chunk_id           TEXT REFERENCES content_chunks(chunk_id) ON DELETE CASCADE,
    resource_id        TEXT,
    page_number        INTEGER,
    start_time         DOUBLE PRECISION,
    end_time           DOUBLE PRECISION,
    quote              TEXT,
    extraction_method  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_edge ON kg_edge_evidence (edge_id);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id       TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    course_id    TEXT NOT NULL,
    resource_id  TEXT,
    status       TEXT NOT NULL,
    stage        TEXT,
    error        TEXT,
    stats        JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON ingestion_jobs (user_id, course_id, started_at);

-- Defence in depth for direct Supabase access: the FastAPI backend uses a service connection,
-- but no anon/authenticated client should read these tables directly.
ALTER TABLE lecture_resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE lecture_segments  ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_chunks    ENABLE ROW LEVEL SECURITY;
ALTER TABLE kg_nodes          ENABLE ROW LEVEL SECURITY;
ALTER TABLE kg_node_aliases   ENABLE ROW LEVEL SECURITY;
ALTER TABLE kg_edges          ENABLE ROW LEVEL SECURITY;
ALTER TABLE kg_edge_evidence  ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_jobs    ENABLE ROW LEVEL SECURITY;
