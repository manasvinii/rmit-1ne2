# Pupil · learn by teaching

> Every AI study tool explains things to you. Pupil flips it: **you** teach a confused AI student, and it finds the gaps in your understanding.

This is our "Innovating Education" hackathon entry, built on top of **RMIT 1NE**, our Canvas-powered study backend. Students pick a week (or several) of their course, tick the lecture material they want to be tested on, then explain it to an AI student who only knows that material. At the end they get an **Understanding Map** showing what they explained well, what was shaky, and what they couldn't explain.

The AI student is grounded in the student's own lecture slides, lab notebooks and recordings, pulled from their own Canvas account.

## What's in the box

| Part | What it does |
| ---- | ------------ |
| **Pupil (teach)** | Teach Pip, Sage or Milo. Every answer is graded as explained, shaky or wrong, with a hint button if you get stuck. |
| **Understanding Map** | A map of the week's ideas, built from the course concept graph, with how well you explained each one. Reteach restarts on just the shaky ideas and gaps. |
| **Ask** | A study chat that answers from your Canvas data (deadlines, courses) and your lecture evidence, with citations. |
| **Brainstorm** | Multiple-choice quizzes written from your own slides, each question citing the slide it came from. |
| **Canvas sync** | Pulls your courses, assignments, modules and files with your own Canvas token. |
| **Ingestion** | Turns slide PDFs, lab notebooks and lecture recordings into searchable chunks and a concept graph. |

### Meet the AI students

| Persona | Style |
| ------- | ----- |
| **Pip**, the curious kid | Needs simple words, asks "but why?", and asks what any jargon means. |
| **Sage**, the sceptic | Won't accept "it just works". Wants a concrete example, the reason, and when it would fail. |
| **Milo**, the mixed-up one | Already believes something wrong about the idea. Defends it once, and lets go only when you clearly explain why it's wrong. |

## Run it locally

You need:

- **Python 3.10 or newer** for the backend
- **Node.js 20 or newer** for the frontend (Angular 21)
- **[Ollama](https://ollama.com)** if you want the AI student to run on your own machine

### One-time setup

**1. Backend**

```
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Open `backend/.env` and set at least:

```
# Point the AI student at your local Ollama server
OPENAI_BASE_URL=http://localhost:11434/v1
LLM_MODEL=<the model you pulled, e.g. llama3.1>

# Lets "Continue with Canvas" sign in as this existing student (ignored in production)
DEMO_USER_EMAIL=<email of a student already in your local database>
```

You don't need to set `JWT_SECRET` or `FERNET_KEY` for local development. The backend generates them on first run and saves them next to the local database (gitignored). Set them yourself in production.

**2. Frontend**

```
cd frontend
npm install
```

**3. Ollama model**

```
ollama pull <the same model name you put in LLM_MODEL>
```

### Start everything

Open three terminals and run these in order.

**Terminal 1: the AI model**

```
ollama serve
```

**Terminal 2: the backend (port 8000)**

```
cd backend
.venv/bin/python -m uvicorn app.main:app --port 8000
```

**Terminal 3: the frontend (port 5173)**

```
cd frontend
npx ng serve --port 5173
```

If `node` isn't on your PATH, add it first, for example `export PATH=/path/to/node/bin:$PATH`.

Then open <http://localhost:5173>.

The frontend talks to the backend at `http://localhost:8000` (set as `API_BASE` in `frontend/src/app/core/api.service.ts`). The backend already allows `http://localhost:5173` through CORS, so you don't need to change anything if you use these ports.

### Check it's working

- <http://localhost:8000/health> should return `status: ok`, and tells you whether an LLM is enabled and which storage is in use.
- On the login screen, click **Continue with Canvas** to sign in as the demo student, or sign up with an email and password.

### Put your own course in

The demo needs a student with ingested course material. Use the command-line tools from `backend/`:

| Command | What it does |
| ------- | ------------ |
| `.venv/bin/python -m app.cli create-user --email you@student.rmit.edu.au --name "Your Name"` | Create a local student |
| `.venv/bin/python -m app.cli ingest --user-id <id> --course-id <course> --dir <folder>` | Ingest lecture PDFs and recordings from a folder |
| `.venv/bin/python -m app.cli canvas-content --user-id <id> --course-id <canvas course id> --ingest` | Download and ingest material from Canvas |
| `.venv/bin/python -m app.cli graph --user-id <id> --course-id <course> --rebuild` | Rebuild the course concept graph |
| `.venv/bin/python -m app.cli ask --user-id <id> "your question"` | Ask a question from the terminal |

### Other commands

| Command | What it does |
| ------- | ------------ |
| `cd backend && make test` | Run the backend test suite |
| `cd backend && make lint` | Lint the backend with ruff |
| `cd frontend && npm run build` | Build the frontend into `dist/` |
| `cd frontend && npm test` | Run the frontend tests |

## Screens

| Route | Screen | What it does |
| ----- | ------ | ------------ |
| `/login` | Login / sign up | Canvas demo button, or email and password with validation |
| `/` | Home | This week's card, streak, your subjects with week strips, and the concepts you keep missing |
| `/setup` | New teaching session | Pick subject, one week, a range or any weeks, tick the files, choose a persona, voice or text, and a length of 10, 15 or 25 minutes |
| `/session` | Teaching session | Teach the AI student by voice or text, ask for a hint, watch the timer, end when you're done |
| `/map` | Understanding Map | Concept map of what you explained well, what was shaky and what you couldn't explain, plus a semester overview |
| `/ask` | Ask Pupil | Study chat with citations back to the slide, page or recording |

All pages except `/login` need you to be signed in. The log-out button is at the bottom of the sidebar.

## How a session works

1. **Scope.** You pick the weeks and tick the files. Everything after this is filtered to that student, course, set of weeks and set of files.
2. **Ideas to teach.** The concept graph tells us which ideas were introduced in those weeks. We keep an idea only if its slide, recording or lab evidence is in the files you ticked. A 10, 15 or 25 minute session covers 4, 5 or 7 ideas.
3. **Teach.** The AI student replies in character and asks the next question. It uses retrieved lecture excerpts to judge your explanation, never to lecture you. You get up to three attempts per idea.
4. **Grade.** Each answer is graded explained, shaky or wrong, with a short piece of feedback and the lecture source it was judged against.
5. **Map.** Ideas are laid out using the concept graph's relations (type of, part of, uses, builds on and so on), coloured by how you did.
6. **Reteach.** Start again on the same weeks and files, focused on just the shaky ideas and gaps.

## Under the hood

```
Canvas ──► sync (courses, assignments, modules, files)
              │
              ▼
   slide PDFs · lab notebooks · recordings (Whisper transcripts)
              │
              ▼
   chunks ──► embeddings (fastembed) ──► vector store
      │
      └────► concept graph (INTRODUCED_IN, BUILDS_ON, USES, ...)
              │
              ▼
   Teaching sessions · Ask · Brainstorm quizzes
   (all scoped to student + course + weeks + ticked files)
```

- **Storage:** local SQLite by default. Set `DATABASE_URL` to a Postgres/Supabase database to use pgvector.
- **LLM:** any OpenAI-compatible endpoint, including a local Ollama server. With no LLM configured, the app still works: replies come from a key-term check, answers are extractive, and the graph uses heuristic extraction.
- **Embeddings:** local `fastembed` by default (`BAAI/bge-small-en-v1.5`).
- **Transcription:** `faster-whisper`, cached by file hash so a recording is only transcribed once.
- **Incremental ingestion:** unchanged files are skipped, changed files are re-processed, and the concept graph is rebuilt.
- **Question routing:** Ask routes each question to Canvas data, vector search, the concept graph, or graph plus vector.

## Security and privacy

- Passwords are hashed with bcrypt.
- Canvas tokens are encrypted at rest and never returned to the client.
- Every route needs a backend-issued bearer token, and the student is never taken from the request body.
- Every lookup checks the student is allowed to see that course.
- Media links are signed and expire.
- Canvas access uses documented REST endpoints only. LTI tools are recorded as external links and never scraped.
- Errors returned to the client never include internals such as SQL or stack traces.
- The demo sign-in is disabled when `APP_ENV=production`.

## Project structure

```
backend/
  app/
    main.py               FastAPI app and routes
    api/                  auth, canvas, ingestion, resources, study, query, academic, pupil
    services/             teaching, ingestion, graph extraction, retrieval, answers,
                          quizzes, Canvas, video, LLM client, query router
    database/             SQLite/Postgres layer, repositories, migrations
    models/               request and graph models
    core/                 config, security, auth
    static/               the original RMIT 1NE study chat page
  tests/                  automated tests
  eval/                   retrieval and answer evaluation
  .env.example            all settings, with comments

frontend/
  src/app/
    pages/                login, home, setup, session, understanding-map, ask
    shared/               layout, avatar, brand, icon, status icon
    core/                 api service, auth, interceptor, models, mock-data
```

**Changing the look:** edit the design tokens at the top of `frontend/src/styles.css`.
**Changing the AI students:** edit `PERSONAS` in `backend/app/services/teaching_service.py`.
**Changing the backend address:** edit `API_BASE` in `frontend/src/app/core/api.service.ts`.

## Settings you're most likely to touch

| Setting (in `backend/.env`) | What it does |
| --------------------------- | ------------ |
| `OPENAI_BASE_URL`, `LLM_MODEL`, `OPENAI_API_KEY` | Which LLM powers the AI student and grading. Leave all empty to run without one. |
| `DEMO_USER_EMAIL` | Student that "Continue with Canvas" signs in as |
| `CURRENT_WEEK` | Force the current teaching week for demos |
| `DATABASE_URL` | Use Postgres/pgvector instead of local SQLite |
| `CORS_ORIGINS` | Frontend addresses the backend accepts |
| `LOCAL_CONTENT_DIR` | The only folder the local ingestion endpoint may read |
| `CANVAS_BASE_URL` | Canvas site (defaults to RMIT's) |

## Known limitations

- Lecture recordings have to be added by hand. A connector for an approved lecture-capture system is defined but not built, because it needs API access granted by the university.
- Quality of the AI student and grading depends on the model you run. Small local models can drift out of character or grade loosely.
- The very first ingestion of a course can take a while, especially for recordings, because they are transcribed on your machine.

## Collaborating

```
git checkout -b your-feature     # make a branch for your work
# ...edit...
git add .
git commit -m "Describe what you changed"
git push -u origin your-feature  # then open a Pull Request on GitHub
```

Never commit your real `backend/.env`.
