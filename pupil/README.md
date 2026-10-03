# Pupil · learn by teaching

> Every AI study tool explains things to you. Pupil flips it: **you** teach a confused AI student, and it finds the gaps in your understanding.

This is the front-end prototype for our "Innovating Education" hackathon entry. Students pick a week (or everything up to a week) of their Canvas course, then explain it out loud to an AI student who only knows that week's material. At the end they get an **Understanding Map** showing what they explained well, what was shaky, and what they couldn't explain.

Everything is mock data right now. There is no backend yet.

## Run it locally

You need **Node.js 18 or newer** ([download](https://nodejs.org)).

```bash
npm install
npm run dev
```

Then open http://localhost:5173.

On the login screen, click **Continue with Canvas** to sign in as the demo student, or type any email plus a password of 6+ characters.

| Command           | What it does                              |
| ----------------- | ----------------------------------------- |
| `npm run dev`     | Start the dev server with hot reload      |
| `npm run build`   | Build a production version into `dist/`   |
| `npm run preview` | Serve the production build locally        |

## Screens

| Route      | Screen                | What works                                                                 |
| ---------- | --------------------- | -------------------------------------------------------------------------- |
| `/login`   | Login / sign up       | Canvas button, email form with validation, show/hide password, sign-up mode |
| `/`        | Home                  | Greeting, this week's hero card, streak, subjects with week strips, gaps   |
| `/setup`   | New teaching session  | Pick subject, single week or range, Canvas files, AI student, voice/text, length |
| `/session` | Teaching session      | Mic toggle with live waveform, typing with canned AI replies, slide hints, timer |
| `/map`     | Understanding Map     | Clickable concept map, breakdown of weak spots, semester overview          |

All pages except `/login` need you to be signed in. The log-out button is at the bottom of the sidebar.

## Project structure

```
src/
  main.jsx              App entry (router + auth provider)
  App.jsx               Routes
  auth.jsx              MOCK login (localStorage). Replace with real auth.
  data/mockData.js      ALL fake data lives here: subjects, weeks, personas, chat script, map
  components/
    AppLayout.jsx       Dark sidebar + page area
    Avatar.jsx          Pip, Sage and Milo (inline SVG)
    Brand.jsx           Logo
    Icon.jsx            Icon set
    StatusIcon.jsx      ✓ / ~ / ! status markers
  pages/
    Login.jsx
    Home.jsx
    Setup.jsx
    Session.jsx
    UnderstandingMap.jsx
  styles/global.css     Design tokens at the top (colours, fonts), then styles per screen
```

**Changing the look:** edit the variables at the top of `src/styles/global.css`.
**Changing the content:** edit `src/data/mockData.js`.

## Known limitations (it's a prototype)

- The teaching conversation and Understanding Map are a **scripted demo about hash tables** (Data Structures, Week 6). Picking another subject or week changes the headers but not the script.
- The AI student's typed replies are canned. Speech is not captured; the mic button only toggles the UI.
- "Draw it", "Share with tutor" and "Save as revision notes" are placeholders.

## Where the real features plug in

| Feature                  | Where in the code                                  | Ideas                                                         |
| ------------------------ | -------------------------------------------------- | ------------------------------------------------------------- |
| Real login               | `src/auth.jsx`                                     | Canvas OAuth2 (developer key), or Firebase / Supabase auth    |
| Canvas courses & files   | `SUBJECTS`, `materialsFor()` in `mockData.js`      | Canvas REST API: courses, modules, files                      |
| AI student replies       | `send()` in `pages/Session.jsx`                    | LLM call with the persona prompt + that week's material       |
| Voice                    | mic button in `pages/Session.jsx`                  | Browser Web Speech API for a quick demo, or a speech-to-text API |
| Understanding Map        | `MAP_NODES` in `mockData.js`                       | Ask the LLM to grade each key idea at the end of the session  |

## Collaborating

```bash
git checkout -b your-feature     # make a branch for your work
# ...edit...
git add .
git commit -m "Describe what you changed"
git push -u origin your-feature  # then open a Pull Request on GitHub
```

## Deploying a live demo

The easiest option is [Vercel](https://vercel.com) or [Netlify](https://netlify.com): import the GitHub repo, keep the defaults (build command `npm run build`, output folder `dist`), and you get a public link to share with judges. Because this app uses client-side routes, Netlify needs a `public/_redirects` file containing `/* /index.html 200`. Vercel detects Vite and handles this for you.
