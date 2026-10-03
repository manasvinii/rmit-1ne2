# Pupil · learn by teaching

> Every AI study tool explains things to you. Pupil flips it: **you** teach a confused AI student, and it finds the gaps in your understanding.

Our "Innovating Education" hackathon entry. Students pick any weeks of their Canvas course (one week, everything up
to a week, or any combination) and tick which materials to use. They then explain the ideas, out loud or typed, to
an AI student who **only knows the ticked material**:

- **Pip**, the curious kid, needs it simple.
- **Sage**, the sceptic, wants mechanisms and proof.
- **Milo**, the mixed-up one, starts with a misconception you have to talk him out of.

At the end they get an **Understanding Map** showing what they explained well, what was shaky, what they couldn't
explain, and which slide to check for each.

```
frontend/   Angular app (the Pupil UI)
backend/    FastAPI: auth, Canvas sync, ingestion (PDF slides, lecture recordings, lab notebooks),
            vector + knowledge-graph retrieval, and the teaching engine behind /api/*
```

## How it works

1. **Canvas → local store.** Course modules and files are synced with the student's own Canvas token, which is
   stored encrypted on the server and never sent to the browser. Slides, uploaded recordings and lab notebooks are
   downloaded and kept aside.
2. **Ingestion.** Each file is split into chunks that remember their page, timestamp or notebook cell. The chunks
   are embedded for search and turned into a **knowledge graph** (concepts, the lecture they were introduced in, and
   what builds on what). Every graph edge cites the chunks it came from.
3. **Setup.** The chosen weeks and ticks become an exact list of allowed resources. Everything the AI student sees
   is filtered to that list.
4. **Teaching.** The session's ideas are the concepts the graph says were introduced in those weeks, provided
   they are backed by the ticked material. Every reply is grounded in retrieved chunks from that material. The
   persona replies with a local LLM (Ollama `qwen2.5:7b`); if no LLM is available, a rule-based fallback is used.
5. **Map.** Each idea is graded as explained, shaky, gap or didn't come up, with the slide or recording moment to
   revisit. Weak spots feed the Home page and the semester strip.

## Run it locally

You need Python 3.12, Node.js 20.19+ / 22.12+, and optionally [Ollama](https://ollama.com) with
`ollama pull qwen2.5:7b` (without it the AI student uses the rule-based fallback).

```bash
# terminal 1: backend on :8000
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # set DEMO_USER_EMAIL for the "Continue with Canvas" demo button
.venv/bin/python -m uvicorn app.main:app --port 8000

# terminal 2: frontend on :5173
cd frontend
npm install
npm start
```

Open http://localhost:5173 and click **Continue with Canvas**. In this demo build that signs you in as the demo
student whose Canvas course has been synced. You can also create an account with email and a password of 8+
characters, then add your Canvas token on the backend (see `backend/README.md`).

Loading your own course content is covered in `backend/README.md` (`python -m app.cli canvas-content --ingest`,
`ingest-labs`).

## Screens

| Route      | Screen               | Backed by                                                                  |
| ---------- | -------------------- | -------------------------------------------------------------------------- |
| `/login`   | Login / sign up      | `POST /login`, `POST /signup`, `POST /api/demo-login`                      |
| `/`        | Home                 | `/api/subjects`, `/api/sessions`, `/api/gaps`, `/me/assignments`, `/canvas/sync` |
| `/setup`   | New teaching session | `/api/subjects/{id}/materials`, `/api/subjects/{id}/download`               |
| `/session` | Teaching session     | `/api/sessions` (start, messages, hint, end); voice via the browser's Web Speech API |
| `/map`     | Understanding Map    | `/api/sessions/{id}/map`, `/api/sessions/{id}/reteach`                      |
| `/ask`     | Ask Pupil (chatbot)  | `POST /query`, which routes each question (see below)                        |

**Ask Pupil** answers any question about your subjects, and every answer cites its sources:

- **Canvas data** (assignments, due dates, course list) answers factual questions like "when is A2 due". These
  answers come straight from the synced tables with no LLM, so dates can't be invented.
- **Vector search** over slide text and video transcripts answers "explain X" questions and links to the exact slide
  or timestamp.
- **The knowledge graph** (concepts, the week that introduced them, prerequisites, what each assignment assesses)
  answers "what's new in week 6", "what should I revise before CNNs" and "which lectures do I need for A2".

A rule-based router picks the source, and the label above each answer shows which one was used. For lecture and
graph questions, the LLM writes the answer only from the retrieved evidence.

Opening `/session` or `/map` directly without a session shows the original scripted demo.

## Known limitations

- Echo360 lecture recordings can't be downloaded; only recordings uploaded to Canvas as files get transcripts.
- Canvas Pages and textbooks are not ingested yet. The current inputs are slides, uploaded recordings and lab
  notebooks.
- Voice input needs a browser with the Web Speech API (Chrome, Edge, Safari). Otherwise use **Type**.
- "Draw it", "Share with tutor" and "Save as revision notes" are still placeholders.
- With the local 7B model, each AI-student reply takes about 5–12 seconds.

## Security

Passwords are bcrypt-hashed and Canvas tokens are encrypted at rest. The browser only holds a short-lived Pupil
session token. Every query is scoped to the signed-in student and their enrolled courses. Never commit `backend/.env`
or `backend/data/` (both are git-ignored).
