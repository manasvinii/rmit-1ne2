# RMIT 1NE backend — hybrid GraphRAG academic assistant

FastAPI service behind the Angular app. It keeps the original features (signup/login, Canvas
courses, classmate finder, n8n chatbot hook) and adds a student-scoped lecture knowledge layer:

```
Angular ──(Bearer JWT)──▶ FastAPI
                           ├── /signup /login /me                bcrypt passwords, Fernet-encrypted Canvas token
                           ├── /me/courses /find_classmate       legacy Supabase tables (or local SQL copy)
                           ├── /canvas/sync, /canvas/.../discover  Canvas REST (courses, assignments, modules metadata)
                           ├── /ingestion/local /ingestion/status  PDFs + recordings from an approved local folder
                           ├── /resources[/{id}/file]            short-lived HMAC-signed file links for citations
                           └── /query ─▶ router ─┬─ STRUCTURED_CANVAS  assignments/deadlines/courses/timetable (+ n8n)
                                                 ├─ VECTOR_RAG        dense (fastembed/pgvector) + keyword, RRF
                                                 ├─ GRAPH             prerequisites / timelines / progression
                                                 └─ GRAPH_VECTOR      graph facts + vector evidence, fused
Ingestion: PDF (PyMuPDF, page provenance) ─┐
           MP4 (faster-whisper, timestamps)┴▶ chunks + embeddings ─▶ content_chunks (user_id, course_id, week, page|time)
                                             └▶ knowledge graph: kg_nodes / kg_edges / kg_edge_evidence (every edge cites chunks)
```

Everything a student can retrieve is filtered by `user_id` taken from the session token and by the
courses they are authorised for — never by a `user_id` in the request.

## Quickstart (local, SQLite)

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # optional for local dev; dev secrets are generated into data/ if empty
.venv/bin/python -m pytest -q   # 95 tests, no network/models needed (hash embeddings, no LLM)
.venv/bin/python -m uvicorn app.main:app --port 8000
```

Frontend: `cd frontend && npm install && npm start` (port 5173; API base is `API_BASE` in
`src/app/core/api.service.ts`). The examples below use `API=http://localhost:8000`.

## Pupil teaching API (`/api`, used by the Angular app)

Every route needs the Bearer token, except `/api/health` and `/api/demo-login`. Every route is scoped to the
signed-in student's enrolled courses.

| Route | What it does |
| ----- | ------------ |
| `POST /api/demo-login` | Demo sign-in as `DEMO_USER_EMAIL`. Disabled when that is unset or `ENV=production`. |
| `GET /api/subjects` | Courses with weekly topics (lecture nodes in the graph), progress strip and current week (`CURRENT_WEEK` or course start date). |
| `GET /api/subjects/{id}/materials?week=&mode=single\|range` or `?weeks=3,6` | Ingested materials for the chosen weeks. Each has a signed file link. Lab notebooks are off by default. |
| `GET /api/subjects/{id}/content`, `/download` | Text of the ticked materials (exactly what the AI student may know), or a zip of the files. |
| `POST /api/sessions` | `{subjectId, week+mode or weeks, persona: pip\|sage\|milo, input, length, exclude, include}`. Picks the ideas (`INTRODUCED_IN` graph facts for those weeks, backed by the ticked files). |
| `POST /api/sessions/{id}/messages` | One teaching turn: retrieval restricted to the session's resources, then the persona LLM reply and a verdict (rule-based fallback). |
| `POST /api/sessions/{id}/hint`, `/end`; `GET /api/sessions/{id}`, `/map` | Hint from the best slide; Understanding Map summary. |
| `POST /api/sessions/{id}/reteach` | New session on the same weeks and material: weak spots only, or everything with `{persona}`. |
| `GET /api/sessions`, `GET /api/gaps` | History and recent weak spots for Home. |

Lab notebooks are ingested with `python -m app.cli ingest-labs --user-id … --course-id …`. Each markdown-headed
section becomes a chunk located by its cell number.

## Ingest the lecture material in this workspace

The current scope uses lecture slides/recordings already available locally (no Canvas media
download). File names like `Lecture 07 NNs.pdf` give the lecture/week; a recording's week is inferred
from which slides its transcript aligns to. An optional `manifest.json` in the folder can set
`{"resources": [{"file": "...", "week": 7, "title": "...", "canvas_url": "..."}]}`.

```bash
.venv/bin/python -m app.cli create-user --email s3999001@student.rmit.edu.au --name "Demo Student" --password demo-pass-123
.venv/bin/python -m app.cli ingest --user-id 3999001 --course-id 171223 --dir /path/to/lectures
.venv/bin/python -m app.cli graph  --user-id 3999001 --course-id 171223 --edges        # inspect the graph
.venv/bin/python -m app.cli graph  --user-id 3999001 --course-id 171223 --rebuild      # rebuild after extractor changes
.venv/bin/python -m app.cli purge-course --user-id 3999001 --course-id OLD_ID          # drop a mis-keyed course
.venv/bin/python -m app.cli ask    --user-id 3999001 "What should I revise before CNNs?"
.venv/bin/python -m app.cli ask    --user-id 3999001 "What was covered in Week 7?"
.venv/bin/python -m app.cli ask    --user-id 3999001 "What lectures do I need for Assessment 2?"
```

Use the **Canvas course id** (e.g. `171223`) as `--course-id`, not the course code. Lecture material and
synced Canvas assignments then share one key, which is what lets assignment specs link to lectures
(`ASSESSES` edges) and keeps similarly named courses (COSC2673 vs COSC2793) apart.

Re-running `ingest` skips unchanged files (sha256 content hash); `--force` reprocesses. Whisper
transcripts are cached in `data/cache/transcripts/` (a 1-hour recording takes about 1–2 minutes on
CPU with `base.en`). A `.vtt`/`.srt`/`.json` transcript next to a video is used instead of Whisper.

## Verify each phase over HTTP

```bash
API=http://localhost:8000
# Phase 1 — auth + /query contract
curl -s -X POST $API/signup -H 'content-type: application/json' \
  -d '{"name":"Demo","email":"s3999002@student.rmit.edu.au","password":"demo-pass-123"}'
TOKEN=$(curl -s -X POST $API/login -H 'content-type: application/json' \
  -d '{"email":"s3999001@student.rmit.edu.au","password":"demo-pass-123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s -X POST $API/query -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"query":"What is ReLU?","course_id":"COSC2673"}'          # -> {reply, sources[], route, confidence}
curl -s -o /dev/null -w '%{http_code}\n' -X POST $API/query -d '{"query":"x"}'   # 401 without a token

# Phase 2 — Canvas (needs a Canvas token stored via signup or PUT /me/canvas-token)
curl -s -X POST $API/canvas/sync -H "authorization: Bearer $TOKEN"
curl -s -X POST $API/canvas/courses/<canvas_course_id>/discover -H "authorization: Bearer $TOKEN"

# Phases 3–4 — ingestion (folder must be inside LOCAL_CONTENT_DIR)
curl -s -X POST $API/ingestion/local -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"course_id":"COSC2673"}'
curl -s $API/ingestion/status -H "authorization: Bearer $TOKEN"
curl -s "$API/resources?course_id=COSC2673" -H "authorization: Bearer $TOKEN"

# Phases 5–6 — graph + routing
curl -s "$API/resources/graph/stats?course_id=COSC2673" -H "authorization: Bearer $TOKEN"
for q in "When is Assignment 2 due?" "Where was gradient descent first introduced?" \
         "What should I revise before CNNs?" "How does Lecture 3 connect to Lecture 7?"; do
  curl -s -X POST $API/query -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
    -d "{\"query\":\"$q\"}" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["route"],d["confidence"]);print(d["reply"][:400])'
done
```

## Evaluation (Phase 8)

`eval/run_eval.py` compares `vector`, `graph` and `hybrid` retrieval on a JSONL question set
(schema in `eval/schema.py`): evidence recall@k / precision@k against gold page or timestamp ranges,
citation correctness, concept recall, route accuracy, latency, and an optional LLM groundedness judge.

```bash
.venv/bin/python -m eval.run_eval --user-id 3999001 --dataset eval/datasets/cosc2673_seed.jsonl --include-draft
```

`eval/datasets/cosc2673_seed.jsonl` holds 10 seed questions whose gold locations were read off the
slide headings; they are marked `draft`. Only `reviewed` items are scored by default — have a
course tutor review labels before quoting any numbers.

## Data model

Migrations: `app/database/migrations/postgres/001_lecture_knowledge.sql` (pgvector, HNSW index, RLS
enabled) and `migrations/sqlite/schema.sql` (local). `migrations/manual/001_legacy_supabase_hardening.sql`
deduplicates the legacy tables, adds unique keys used by Canvas upserts and enables RLS.

| table | purpose |
|---|---|
| `lecture_resources` | one row per PDF / recording / Canvas item: owner, course, week, provider, `is_external`, content hash, status |
| `lecture_segments` | raw transcript segments with start/end seconds |
| `content_chunks` | retrievable chunks with page range or timestamps and a 384-d embedding |
| `kg_nodes` / `kg_node_aliases` | Student, Course, Lecture, Resource, Concept/Topic, Assignment; aliases ("GD") |
| `kg_edges` / `kg_edge_evidence` | typed relations with confidence and extraction method; evidence rows point at chunks, pages, timestamps, quotes |
| `ingestion_jobs` | per-stage job log |

The graph lives in Postgres tables queried with recursive CTEs (`GraphRepository`), so one database
holds vectors, graph and provenance and every query carries the same `user_id`/course filter.

## Security

- Passwords: bcrypt. Legacy plaintext rows are upgraded on the next successful login.
- The app never asks for RMIT SSO passwords. Canvas access uses a Canvas access token the student
  generates (or, preferably, a Canvas Developer Key OAuth2 flow — see below). Tokens are encrypted
  at rest with Fernet (`enc:v1:` prefix), never returned to the browser, and redacted from logs.
- Sessions: HS256 JWT (`JWT_SECRET`), identity only from `Authorization: Bearer`.
- Every chunk, graph and resource query requires `user_id`; course access is checked per request
  (`authorised_courses`). Cross-student isolation is covered by `tests/test_isolation.py`.
- Citation links are HMAC-signed, user-bound and expire (`SIGNED_URL_TTL_SECONDS`).
- PDFs and videos are checked for extension, magic bytes and size limits; the ingestion endpoint
  only reads inside `LOCAL_CONTENT_DIR`.
- In `APP_ENV=production`, missing `JWT_SECRET`/`FERNET_KEY` is a startup error.

## What RMIT would need to approve

- **Canvas OAuth2**: a Canvas Developer Key issued by RMIT's Canvas admins (scopes: courses,
  assignments, modules, files read) to replace personal access tokens.
- **Lecture recordings**: recordings embedded as LTI tools (e.g. Echo360/Kaltura/Panopto) are
  discovered as `ExternalTool` items and marked `is_external`; they are **not** downloaded. Ingesting
  them needs the provider's official API or caption export approved by RMIT (an implementation
  slot exists as `LectureCaptureProvider` in `services/providers.py`). The app does not scrape
  or bypass provider authentication.
- **Supabase**: run the hardening migration and use a service key server-side only; RLS policies
  for direct client access are not part of this change.

## Known limitations

- The Postgres/pgvector path is implemented but was not exercised against a live Supabase instance
  here; tests and the demo run on SQLite.
- No LLM key was configured during development, so answers are extractive and the graph comes from
  heuristic extraction. With `OPENAI_API_KEY` set, LLM extraction is used and every LLM relation is
  validated: allowed relation types only, and the evidence quote must appear in the chunk.
- Grades are not synced from Canvas yet; the assistant says so instead of guessing.
- Week inference for recordings depends on slide alignment; set `week` in `manifest.json` when known.
