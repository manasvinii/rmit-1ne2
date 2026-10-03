# Pupil · frontend (Angular)

Students pick a week of their Canvas course, then teach it to an AI student. Every screen is an
Angular component with its own **`.html`** (layout), **`.ts`** (logic) and **`.css`** (styles).

## Run it

You need Node.js 20.19+, 22.12+ or 24+.

```bash
cd frontend
npm install        # first time only
npm start          # = ng serve, opens on http://localhost:5173
```

The backend must be running too (in another terminal):

```bash
cd backend
.venv/bin/python -m uvicorn app.main:app --port 8000
```

On the login screen click **Continue with Canvas**. That is the demo login: it needs `DEMO_USER_EMAIL` in
`backend/.env`. You can also sign in or create an account with email and a password (8+ characters for sign-up).

| Command         | What it does                              |
| --------------- | ----------------------------------------- |
| `npm start`     | Dev server with live reload on port 5173  |
| `npm run build` | Production build into `dist/frontend/`    |

## Where things are

```
src/
  index.html                 Page shell + Google Fonts
  styles.css                 ALL the design: colours, fonts and every screen's styles
  app/
    app.routes.ts            Which URL shows which page (+ login guard)
    app.config.ts            Router + HttpClient (with the auth interceptor)
    core/
      api.service.ts         Calls to the backend (subjects, materials, sessions, map, gaps, downloads)
      auth.service.ts        Login / sign-up / demo login; keeps only the backend session token
      auth.interceptor.ts    Adds the Bearer token; an expired session goes back to /login
      auth.guard.ts          Sends signed-out users to /login
      models.ts              TypeScript types (Subject, Material, TeachingSession, UnderstandingMapData, ...)
      mock-data.ts           Personas, plus the scripted demo shown when the backend is unreachable
    shared/
      app-layout/            Dark sidebar + page area (Home, Setup, Map)
      icon/                  <svg appIcon name="mic">
      avatar/                <svg appAvatar persona="pip">  (Pip, Sage, Milo)
      status-icon/           <span appStatusIcon status="G">  (✓ ~ ! markers)
      brand/                 <app-brand> logo
    pages/
      login/                 login.html · login.ts · login.css
      home/                  Greeting, subjects from Canvas, gaps
      setup/                 Choose subject, weeks (one / up to / pick any), Canvas materials, AI student
      session/               Teaching chat with the AI student; voice via Web Speech API
      understanding-map/     Results map, weak spots, semester strip, re-teach
```

## What's real and what's still demo

| Screen  | From the backend                                                                 | Still placeholder             |
| ------- | -------------------------------------------------------------------------------- | ----------------------------- |
| Sidebar | "Canvas connected" card: subject count, current week                             |                               |
| Home    | Subjects, week strip, hero, streak, ideas explained, next Canvas deadline, gaps   |                               |
| Setup   | Subjects, weeks, topics, materials, file links, "Download all"                   |                               |
| Session | Ideas, conversation, hints, source slide / recording, confusion meter, notebook   | "Draw it"                     |
| Map     | Concept tree, breakdown, toughest question, score, semester strip, re-teach      | Share / save buttons          |

A session survives a page reload: its id is kept in the URL (`/session?id=…`, `/map?session=…`).
Opening those pages with no session shows the original scripted demo.

The backend address is `API_BASE` in `src/app/core/api.service.ts`.
