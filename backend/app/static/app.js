// RMIT 1NE study assistant — single-page UI served by the FastAPI backend (no build step).

const API = "";
const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ icons
const I = {
  plus: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
  chat: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
  spark: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>',
  grid: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>',
  cal: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
  send: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
  out: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>',
  slides: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>',
  video: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="15" height="14" rx="2"/><path d="m17 10 5-3v10l-5-3"/></svg>',
  canvas: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5V21h16"/></svg>',
  copy: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
  redo: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>',
  trash: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>',
  ext: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3"/></svg>',
  book: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2zM22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/></svg>',
  path: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M8 19h8.5a3.5 3.5 0 0 0 0-7h-9a3.5 3.5 0 0 1 0-7H16"/></svg>',
  target: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></svg>',
  clock: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
};

// ------------------------------------------------------------------ state
const state = {
  session: JSON.parse(localStorage.getItem("rmit1ne.session") || "null"),
  view: "chat",
  courses: [], weeks: [], assignments: [], health: null,
  courseId: localStorage.getItem("rmit1ne.course") || "",
  aiOn: localStorage.getItem("rmit1ne.ai") !== "off",
  chats: [], chatId: null, busy: false,
  quiz: null, quizSetup: { mode: "assignment", assignmentId: "", week: "", n: 5 }, quizBusy: false,
};

const chatsKey = () => `rmit1ne.chats.${state.session?.user_id}`;
const loadChats = () => { state.chats = JSON.parse(localStorage.getItem(chatsKey()) || "[]"); };
const saveChats = () => localStorage.setItem(chatsKey(), JSON.stringify(state.chats.slice(0, 40)));
const currentChat = () => state.chats.find((c) => c.id === state.chatId);

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2200);
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.session?.token) headers.Authorization = `Bearer ${state.session.token}`;
  const res = await fetch(API + path, { ...opts, headers });
  if (res.status === 401 && state.session) { logout(); throw new Error("Session expired, please sign in again."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data;
}

function logout() {
  localStorage.removeItem("rmit1ne.session");
  state.session = null;
  render();
}

// ------------------------------------------------------------------ formatting
const ROUTE = { STRUCTURED_CANVAS: "Canvas data", VECTOR_RAG: "Lecture search", GRAPH: "Knowledge graph", GRAPH_VECTOR: "Graph + lectures" };
const INTENT = {
  week_overview: "Week overview", assignment_revision: "Assignment planner", prerequisites: "Revision path",
  deadline: "Deadlines", assignment_list: "Assignments", course_list: "Courses", lecture_fact: "From your lectures",
  locate: "Find in lectures", concept_timeline: "Concept timeline", lecture_connection: "Lecture connections",
};

function fmtDue(iso) {
  if (!iso) return "No due date";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

function relDue(iso) {
  if (!iso) return "";
  const ms = new Date(iso) - new Date();
  const h = Math.round(Math.abs(ms) / 36e5);
  const txt = h < 1 ? "under an hour" : h < 48 ? `${h} hour${h === 1 ? "" : "s"}` : `${Math.round(h / 24)} days`;
  return ms >= 0 ? `due in ${txt}` : `${txt} ago`;
}

function inline(s) {
  return s
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\[(S|C)(\d+)\]/g, (_, k, n) => `<button class="cite ${k === "C" ? "canvas" : ""}" data-cite="${k}${n}">${k === "C" ? "C" : ""}${n}</button>`);
}

// Small markdown subset: paragraphs, bullet/numbered lists, "Heading:" lines, quotes, bold, citations.
function md(text) {
  const lines = esc(text).split("\n");
  let html = "", list = null;
  const close = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*(?:[•\-*▪])\s+(.*)$/);
    const num = line.match(/^\s*(\d+)[.)]\s+(.*)$/);
    if (bullet || num) {
      const tag = bullet ? "ul" : "ol";
      if (list !== tag) { close(); html += `<${tag}>`; list = tag; }
      html += `<li>${inline((bullet || num)[bullet ? 1 : 2])}</li>`;
      continue;
    }
    close();
    if (!line.trim()) continue;
    if (/^&gt;\s?/.test(line)) html += `<blockquote>${inline(line.replace(/^&gt;\s?/, ""))}</blockquote>`;
    else if (/^[^.!?]{2,70}:$/.test(line.trim())) html += `<h4>${inline(line.trim().slice(0, -1))}</h4>`;
    else html += `<p>${inline(line)}</p>`;
  }
  close();
  return html;
}

function srcMeta(s) {
  const bits = [];
  if (s.week) bits.push(`Week ${s.week}`);
  if (s.type === "video" && s.timestamp) bits.push(s.timestamp);
  else if (s.page) bits.push(`slide ${s.page}${s.page_end ? `–${s.page_end}` : ""}`);
  if (s.type === "canvas") bits.push("Canvas");
  return bits.join(" · ");
}

function sourceCard(s) {
  const kind = s.type === "video" ? "video" : s.type === "canvas" ? "canvas" : "slides";
  const tag = s.url ? "a" : "div";
  const href = s.url ? ` href="${esc(s.url)}" target="_blank" rel="noopener"` : "";
  return `<${tag} class="src" data-src="${esc(s.id)}"${href}>
    <div class="src-top"><span class="src-ic ${kind}">${I[kind]}</span><span class="src-title">${esc(s.title)}</span><span class="src-id">${esc(s.id)}</span></div>
    <div class="src-meta">${esc(srcMeta(s))}${s.support === "inferred" ? " · inferred link" : ""}</div>
    ${s.snippet ? `<div class="src-snip">${esc(s.snippet)}</div>` : ""}
    ${s.relation ? `<div class="src-rel">${esc(s.relation)}</div>` : ""}
  </${tag}>`;
}

// ------------------------------------------------------------------ login
function renderLogin(error = "") {
  $("#app").innerHTML = `
  <div class="login">
    <section class="login-brand">
      <div class="brand" style="padding:0"><div class="logo" style="background:#fff;color:var(--red)">1NE</div><div><b>RMIT 1NE</b><small style="color:#ffd6dd">Study Assistant</small></div></div>
      <div>
        <h1>Your lectures, assignments and Canvas — in one conversation.</h1>
        <p>Ask anything about your courses. Every answer points to the exact slide or moment in the recording it came from.</p>
        <div class="login-feats">
          <div class="login-feat">${I.book}<div><b>Week-by-week recaps</b><span>What each lecture covered, what's new and what's revision.</span></div></div>
          <div class="login-feat">${I.target}<div><b>Assignment planner</b><span>Reads the Canvas spec and tells you which lectures you need.</span></div></div>
          <div class="login-feat">${I.spark}<div><b>Brainstorm quizzes</b><span>Practice questions from your notes, aimed at the assignment.</span></div></div>
        </div>
      </div>
      <small style="opacity:.75">Your Canvas token stays encrypted on the server and is never sent to the browser.</small>
    </section>
    <section class="login-form-wrap">
      <form class="login-form" id="login">
        <h2>Welcome back</h2>
        <p class="sub">Sign in with your RMIT 1NE account.</p>
        ${error ? `<div class="error">${esc(error)}</div>` : ""}
        <div class="field"><label>Email</label><input class="input" name="email" type="email" autocomplete="username" required placeholder="s1234567@student.rmit.edu.au"></div>
        <div class="field"><label>Password</label><input class="input" name="password" type="password" autocomplete="current-password" required></div>
        <button class="btn btn-primary btn-block" type="submit">Sign in</button>
        <div class="divider">or</div>
        <button class="btn btn-ghost btn-block" type="button" id="demo">Use the demo student account</button>
      </form>
    </section>
  </div>`;
  const form = $("#login");
  $("#demo").onclick = () => { form.email.value = "s3999001@student.rmit.edu.au"; form.password.value = "demo-pass-123"; form.requestSubmit(); };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true; btn.textContent = "Signing in…";
    try {
      const r = await api("/login", { method: "POST", body: JSON.stringify({ email: form.email.value, password: form.password.value }) });
      state.session = { token: r.access_token, user_id: r.user_id, name: r.name || "Student", exp: Date.now() + r.expires_in * 1000 };
      localStorage.setItem("rmit1ne.session", JSON.stringify(state.session));
      await boot();
    } catch (err) {
      renderLogin(err.message);
    }
  };
}

// ------------------------------------------------------------------ shell
async function boot() {
  loadChats();
  render();
  const [courses, weeks, assignments, health] = await Promise.all([
    api("/me/courses").catch(() => []), api("/me/weeks").catch(() => []),
    api("/me/assignments").catch(() => []), api("/health").catch(() => null),
  ]);
  Object.assign(state, { courses, weeks, assignments, health });
  const withNotes = new Set(weeks.map((w) => w.course_id));
  if (!state.courseId && withNotes.size === 1) state.courseId = [...withNotes][0];
  if (state.courseId && !courses.some((c) => String(c.id) === state.courseId)) state.courseId = "";
  render();
}

function courseName(id) {
  const c = state.courses.find((c) => String(c.id) === String(id));
  return c ? c.name.replace(/\s*\(\d+\)\s*$/, "") : "";
}

function render() {
  if (!state.session || state.session.exp < Date.now()) return renderLogin();
  const first = (state.session.name || "S").trim()[0].toUpperCase();
  const upcoming = state.assignments.filter((a) => a.upcoming).length;
  const notes = new Set(state.weeks.map((w) => w.course_id));
  const courseOpts = [
    `<option value="">All my courses</option>`,
    ...state.courses.filter((c) => notes.has(String(c.id))).map((c) => `<option value="${esc(c.id)}" ${String(c.id) === state.courseId ? "selected" : ""}>${esc(c.name)} · lecture notes</option>`),
    ...state.courses.filter((c) => !notes.has(String(c.id))).map((c) => `<option value="${esc(c.id)}" ${String(c.id) === state.courseId ? "selected" : ""}>${esc(c.name)}</option>`),
  ].join("");
  const titles = { chat: currentChat()?.title || "New chat", brainstorm: "Brainstorm", weeks: "Course map", deadlines: "Deadlines" };
  $("#app").innerHTML = `
  <div class="shell">
    <aside class="side">
      <div class="brand"><div class="logo">1NE</div><div><b>RMIT 1NE</b><small>Study Assistant</small></div></div>
      <button class="btn newchat" id="new">${I.plus} New chat</button>
      <nav class="nav">
        <button data-view="chat" class="${state.view === "chat" ? "active" : ""}">${I.chat} Chat</button>
        <button data-view="brainstorm" class="${state.view === "brainstorm" ? "active" : ""}">${I.spark} Brainstorm</button>
        <button data-view="weeks" class="${state.view === "weeks" ? "active" : ""}">${I.grid} Course map</button>
        <button data-view="deadlines" class="${state.view === "deadlines" ? "active" : ""}">${I.cal} Deadlines ${upcoming ? `<span class="pill">${upcoming}</span>` : ""}</button>
      </nav>
      <div class="side-label">Recent</div>
      <div class="history">${state.chats.length ? state.chats.map((c) => `
        <button data-chat="${c.id}" class="${c.id === state.chatId && state.view === "chat" ? "active" : ""}"><span>${esc(c.title)}</span><i class="del" data-del="${c.id}" title="Delete">${I.trash}</i></button>`).join("")
        : `<div class="empty">Your conversations will appear here.</div>`}</div>
      <div class="me"><div class="avatar">${esc(first)}</div><div class="who"><b>${esc(state.session.name)}</b><small>Student ${esc(state.session.user_id)}</small></div>
        <button class="icon-btn" id="logout" title="Sign out">${I.out}</button></div>
    </aside>
    <main class="main">
      <header class="topbar">
        <h3>${esc(titles[state.view])}</h3>
        <div class="spacer"></div>
        <select class="select" id="course" title="Which course to focus on">${courseOpts}</select>
        <label class="toggle ${state.aiOn ? "on" : ""}" id="ai" title="${state.aiOn ? "Answers are written by the local AI model" : "Instant answers built straight from your slides"}">
          <span class="switch"></span>${state.aiOn ? `AI answers${state.health?.llm_model ? ` · ${esc(state.health.llm_model)}` : ""}` : "Instant mode"}
        </label>
      </header>
      <div class="content" id="content"></div>
      ${state.view === "chat" ? `<div class="composer-wrap"><form class="composer" id="composer">
          <textarea id="q" rows="1" placeholder="Ask about a lecture, a week, an assignment or a deadline…"></textarea>
          <button class="send" id="send" type="submit" disabled>${I.send}</button></form>
        <div class="disclaimer">Answers cite your own lecture slides, recordings and Canvas data. Check the sources for anything important.</div></div>` : ""}
    </main>
  </div>`;

  $("#new").onclick = () => { state.chatId = null; state.view = "chat"; render(); $("#q")?.focus(); };
  $("#logout").onclick = logout;
  document.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => { state.view = b.dataset.view; render(); }));
  document.querySelectorAll("[data-chat]").forEach((b) => (b.onclick = (e) => {
    if (e.target.closest("[data-del]")) {
      state.chats = state.chats.filter((c) => c.id !== e.target.closest("[data-del]").dataset.del);
      if (!currentChat()) state.chatId = null;
      saveChats(); render(); return;
    }
    state.chatId = b.dataset.chat; state.view = "chat"; render();
  }));
  $("#course").onchange = (e) => { state.courseId = e.target.value; localStorage.setItem("rmit1ne.course", state.courseId); state.quiz = null; render(); };
  $("#ai").onclick = () => { state.aiOn = !state.aiOn; localStorage.setItem("rmit1ne.ai", state.aiOn ? "on" : "off"); render(); };

  ({ chat: renderChat, brainstorm: renderBrainstorm, weeks: renderWeeks, deadlines: renderDeadlines })[state.view]();
}

// ------------------------------------------------------------------ chat
function suggestions() {
  const a = state.assignments.find((x) => x.upcoming && x.linked_to_lectures) || state.assignments.find((x) => x.linked_to_lectures);
  const lastWeek = Math.max(0, ...state.weeks.map((w) => w.week || 0));
  return [
    { ic: "ic-red", icon: I.book, t: `What was covered in Week ${lastWeek > 7 ? 7 : lastWeek || 7}?`, s: "Week-by-week recap with slides and recording" },
    { ic: "ic-blue", icon: I.target, t: `What lectures do I need for ${a ? a.name : "Assessment 2"}?`, s: "Reads the assignment spec from Canvas" },
    { ic: "ic-green", icon: I.path, t: "What should I revise before neural networks?", s: "A revision path through earlier topics" },
    { ic: "ic-amber", icon: I.clock, t: "When is my next assignment due?", s: "Straight from your Canvas courses" },
  ];
}

function renderChat() {
  const chat = currentChat();
  const content = $("#content");
  if (!chat) {
    const hour = new Date().getHours();
    const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    content.innerHTML = `<div class="hero">
      <h1>${greet}, <em>${esc((state.session.name || "").split(" ")[0])}</em></h1>
      <p>Ask about your lectures, a specific week, or what an assignment needs. I'll show you exactly where each answer comes from.</p>
      <div class="suggest">${suggestions().map((s) => `<button data-ask="${esc(s.t)}"><span class="ic ${s.ic}">${s.icon}</span><div><b>${esc(s.t)}</b><span>${esc(s.s)}</span></div></button>`).join("")}</div>
    </div>`;
  } else {
    content.innerHTML = `<div class="thread">${chat.messages.map((m, i) => renderMessage(m, i)).join("")}</div>`;
  }
  wireChat();
  content.scrollTop = content.scrollHeight;
}

function renderMessage(m, i) {
  if (m.role === "user") return `<div class="msg user"><div class="bubble">${esc(m.text)}</div></div>`;
  if (m.pending) return `<div class="msg"><div class="bot-av">1NE</div><div class="body"><div class="thinking"><span class="dots"><i></i><i></i><i></i></span><span id="step">${esc(m.step || "Understanding your question…")}</span></div></div></div>`;
  if (m.error) return `<div class="msg"><div class="bot-av">1NE</div><div class="body"><div class="note">${esc(m.error)}</div></div></div>`;
  const r = m.resp;
  const conf = r.confidence >= 0.75 ? "conf-high" : r.confidence >= 0.5 ? "conf-mid" : "conf-low";
  const confTxt = r.confidence >= 0.75 ? "High confidence" : r.confidence >= 0.5 ? "Medium confidence" : "Low confidence";
  const course = [...new Set(r.sources.map((s) => s.course_id).filter(Boolean))].map(courseName).filter(Boolean)[0];
  return `<div class="msg" data-msg="${i}"><div class="bot-av">1NE</div><div class="body">
    <div class="meta-row"><span class="tag route">${esc(ROUTE[r.route] || r.route)}</span>${r.intent ? `<span class="tag">${esc(INTENT[r.intent] || r.intent)}</span>` : ""}
      <span class="tag ${conf}">${confTxt}</span>${course ? `<span class="tag">${esc(course)}</span>` : ""}${m.fast ? `<span class="tag">Instant</span>` : ""}</div>
    <div class="answer">${md(r.reply.replace(/\n*Sources:[\s\S]*$/, ""))}</div>
    ${r.notes?.length ? `<div class="notes">${r.notes.map((n) => `<div class="note">${esc(n)}</div>`).join("")}</div>` : ""}
    ${r.sources.length ? `<div class="sources-head">${r.sources.length} source${r.sources.length > 1 ? "s" : ""}</div><div class="sources">${r.sources.map(sourceCard).join("")}</div>` : ""}
    <div class="actions"><button data-copy="${i}">${I.copy} Copy</button><button data-redo="${i}">${I.redo} Regenerate</button></div>
  </div></div>`;
}

function wireChat() {
  const q = $("#q"), send = $("#send"), form = $("#composer");
  document.querySelectorAll("[data-ask]").forEach((b) => (b.onclick = () => ask(b.dataset.ask)));
  if (q) {
    const grow = () => { q.style.height = "auto"; q.style.height = Math.min(q.scrollHeight, 200) + "px"; send.disabled = !q.value.trim() || state.busy; };
    q.oninput = grow;
    q.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } };
    form.onsubmit = (e) => { e.preventDefault(); if (q.value.trim() && !state.busy) ask(q.value.trim()); };
    if (!state.busy) q.focus();
  }
  document.querySelectorAll(".cite").forEach((c) => {
    const msg = c.closest("[data-msg]");
    const card = msg && msg.querySelector(`[data-src="${c.dataset.cite}"]`);
    c.onmouseenter = () => card?.classList.add("hl");
    c.onmouseleave = () => card?.classList.remove("hl");
    c.onclick = () => { if (card?.href) window.open(card.href, "_blank", "noopener"); else card?.scrollIntoView({ behavior: "smooth", block: "nearest" }); };
  });
  document.querySelectorAll("[data-copy]").forEach((b) => (b.onclick = () => {
    navigator.clipboard.writeText(currentChat().messages[+b.dataset.copy].resp.reply); toast("Copied");
  }));
  document.querySelectorAll("[data-redo]").forEach((b) => (b.onclick = () => {
    const chat = currentChat(), i = +b.dataset.redo;
    const question = chat.messages[i - 1]?.text;
    chat.messages.splice(i - 1, 2); saveChats();
    if (question) ask(question);
  }));
}

const STEPS = ["Understanding your question…", "Searching your lecture notes…", "Following the knowledge graph…", "Checking the evidence…", "Writing a cited answer…"];

async function ask(text) {
  if (state.busy) return;
  state.view = "chat";
  let chat = currentChat();
  if (!chat) {
    chat = { id: crypto.randomUUID(), title: text.length > 48 ? text.slice(0, 46) + "…" : text, messages: [], courseId: state.courseId };
    state.chats.unshift(chat); state.chatId = chat.id;
  }
  chat.messages.push({ role: "user", text });
  const pending = { role: "assistant", pending: true, step: STEPS[0] };
  chat.messages.push(pending);
  state.busy = true;
  render();
  let k = 0;
  const timer = setInterval(() => { k = Math.min(k + 1, STEPS.length - 1); const el = $("#step"); if (el) el.textContent = STEPS[k]; }, 2200);
  const fast = !state.aiOn;
  try {
    const resp = await api("/query", { method: "POST", body: JSON.stringify({ query: text, course_id: state.courseId || null, fast }) });
    Object.assign(pending, { pending: false, resp, fast });
  } catch (err) {
    Object.assign(pending, { pending: false, error: err.message });
  } finally {
    clearInterval(timer);
    state.busy = false;
    state.chats = [chat, ...state.chats.filter((c) => c.id !== chat.id)];
    saveChats();
    if (state.session) render();
  }
}

// ------------------------------------------------------------------ brainstorm
function renderBrainstorm() {
  const s = state.quizSetup;
  const inCourse = (cid) => !state.courseId || String(cid) === state.courseId;
  const assignments = state.assignments.filter((a) => a.linked_to_lectures && a.has_spec && inCourse(a.course_id));
  const weeks = state.weeks.filter((w) => inCourse(w.course_id));
  if (!s.assignmentId && assignments.length) s.assignmentId = (assignments.find((a) => a.upcoming) || assignments[0]).id;
  if (!s.week && weeks.length) s.week = String(weeks[0].week);
  const q = state.quiz;
  $("#content").innerHTML = `<div class="page">
    <div class="page-head"><div class="ic ic-red">${I.spark}</div><div><h2>Brainstorm</h2>
      <p>Practice questions written from your lecture notes, aimed at what the assignment spec asks for.</p></div></div>
    <div class="card setup">
      <div class="seg"><button data-mode="assignment" class="${s.mode === "assignment" ? "on" : ""}">From an assignment</button><button data-mode="week" class="${s.mode === "week" ? "on" : ""}">From a week</button></div>
      <div class="setup-row">
        ${s.mode === "assignment"
          ? `<select class="select" id="qa">${assignments.length ? assignments.map((a) => `<option value="${esc(a.id)}" ${a.id === s.assignmentId ? "selected" : ""}>${esc(a.name)} — ${esc(courseName(a.course_id))}${a.upcoming ? ` · ${esc(relDue(a.due_at))}` : ""}</option>`).join("") : `<option value="">No assignments linked to your lecture notes yet</option>`}</select>`
          : `<select class="select" id="qw">${weeks.map((w) => `<option value="${w.week}" ${String(w.week) === String(s.week) ? "selected" : ""}>${esc(w.label)}</option>`).join("") || `<option value="">No lecture weeks yet</option>`}</select>`}
        <div class="chips">${[3, 5, 8].map((n) => `<button class="chip ${s.n === n ? "on" : ""}" data-n="${n}">${n} questions</button>`).join("")}</div>
        <button class="btn btn-primary" id="gen" ${state.quizBusy ? "disabled" : ""}>${I.spark} ${q ? "New quiz" : "Generate quiz"}</button>
      </div>
      <div class="hint">${state.aiOn ? "The local AI writes the questions from your slides (about 30–60 seconds)." : "Instant mode: questions are built straight from your slides."} Every question links to the slide it came from.</div>
    </div>
    <div id="quiz"></div>
  </div>`;
  document.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => { s.mode = b.dataset.mode; render(); }));
  document.querySelectorAll("[data-n]").forEach((b) => (b.onclick = () => { s.n = +b.dataset.n; render(); }));
  $("#qa") && ($("#qa").onchange = (e) => (s.assignmentId = e.target.value));
  $("#qw") && ($("#qw").onchange = (e) => (s.week = e.target.value));
  $("#gen").onclick = generateQuiz;
  renderQuiz();
}

async function generateQuiz() {
  const s = state.quizSetup;
  state.quizBusy = true; state.quiz = null;
  render();
  $("#quiz").innerHTML = `<div class="loading-note"><span class="dots"><i></i><i></i><i></i></span>${s.mode === "assignment" ? "Reading the assignment spec and matching it to your slides…" : "Reading that week's slides…"}</div>
    <div class="skeleton"></div><div class="skeleton"></div>`;
  try {
    const body = { num_questions: s.n, fast: !state.aiOn, course_id: state.courseId || null };
    if (s.mode === "assignment") body.assignment_id = s.assignmentId; else body.week = +s.week;
    state.quiz = { ...(await api("/brainstorm/quiz", { method: "POST", body: JSON.stringify(body) })), answers: {} };
  } catch (err) {
    state.quiz = { error: err.message };
  } finally {
    state.quizBusy = false;
    if (state.view === "brainstorm") render();
  }
}

function renderQuiz() {
  const q = state.quiz, el = $("#quiz");
  if (!q || !el) return;
  if (q.error) { el.innerHTML = `<div class="note" style="margin-top:16px">${esc(q.error)}</div>`; return; }
  const src = Object.fromEntries((q.sources || []).map((s) => [s.id, s]));
  const total = q.questions.length, answered = Object.keys(q.answers).length;
  const correct = q.questions.filter((x) => q.answers[x.id] === x.answer_index).length;
  const f = q.focus;
  const assessed = q.concepts.filter((c) => c.assessed), extra = q.concepts.filter((c) => !c.assessed);
  el.innerHTML = `
    <div class="card focus">
      <div><h3>${esc(f.name)}</h3><div class="sub">${f.kind === "assignment" ? `${esc(courseName(f.course_id))}${f.due_at ? ` · due ${esc(fmtDue(f.due_at))}` : ""}` : "Concepts introduced this week"}${q.method === "llm" ? " · questions written by AI from your slides" : " · questions built from your slides"}</div></div>
      ${assessed.length ? `<div><div class="hint" style="margin-bottom:6px">What the spec asks for</div><div class="concepts">${assessed.map((c) => `<span class="concept assessed">${esc(c.concept)}${c.week ? `<small>W${c.week}</small>` : ""}</span>`).join("")}</div></div>` : ""}
      ${extra.length ? `<div><div class="hint" style="margin-bottom:6px">${f.kind === "assignment" ? "Foundations it builds on" : "Covered"}</div><div class="concepts">${extra.map((c) => `<span class="concept">${esc(c.concept)}${c.week ? `<small>W${c.week}</small>` : ""}</span>`).join("")}</div></div>` : ""}
    </div>
    <div class="progress"><span>${answered} / ${total} answered</span><div class="bar"><i style="width:${total ? (answered / total) * 100 : 0}%"></i></div><span>${correct} correct</span></div>
    ${q.questions.map((x, n) => {
      const picked = q.answers[x.id];
      const done = picked !== undefined;
      const s = src[x.source_id];
      return `<div class="card q">
        <div class="q-head"><span class="q-num">Q${n + 1}</span><span class="tag">${esc(x.concept)}</span>${x.week ? `<span class="tag">Week ${x.week}</span>` : ""}</div>
        <p class="q-text">${esc(x.question)}</p>
        <div class="opts">${x.options.map((o, i) => {
          const cls = done ? (i === x.answer_index ? "right" : i === picked ? "wrong" : "") : "";
          return `<button class="opt ${cls}" data-q="${x.id}" data-i="${i}" ${done ? "disabled" : ""}><span class="k">${"ABCD"[i]}</span><span>${esc(o)}</span></button>`;
        }).join("")}</div>
        ${done ? `<div class="reveal">
          <div class="explain"><b>${picked === x.answer_index ? "Correct." : `Not quite — the answer is ${"ABCD"[x.answer_index]}.`}</b> ${esc(x.explanation)}</div>
          ${x.spec_quote && f.kind === "assignment" ? `<div class="why"><b>Why it matters for ${esc(f.name)}:</b> “${esc(x.spec_quote.slice(0, 220))}”</div>` : ""}
          ${s ? `<a class="src-link" ${s.url ? `href="${esc(s.url)}" target="_blank" rel="noopener"` : ""}>${I.slides} ${esc(s.title)} · ${esc(srcMeta(s))} ${s.url ? I.ext : ""}</a>` : ""}
        </div>` : ""}
      </div>`;
    }).join("")}
    ${answered === total && total ? summaryCard(q, correct, total) : ""}`;
  el.querySelectorAll(".opt:not(:disabled)").forEach((b) => (b.onclick = () => {
    q.answers[b.dataset.q] = +b.dataset.i;
    const y = $("#content").scrollTop;
    renderQuiz();
    $("#content").scrollTop = y;
  }));
  el.querySelectorAll("[data-explain]").forEach((b) => (b.onclick = () => { state.chatId = null; ask(`Explain ${b.dataset.explain}`); }));
}

function summaryCard(q, correct, total) {
  const pct = Math.round((correct / total) * 100);
  const wrong = q.questions.filter((x) => q.answers[x.id] !== x.answer_index);
  const colour = pct >= 80 ? "var(--green)" : pct >= 50 ? "var(--amber)" : "var(--red)";
  return `<div class="card summary">
    <div class="ring" style="background:conic-gradient(${colour} ${pct * 3.6}deg, var(--line) 0)"><div>${correct}/${total}</div></div>
    <div><h3>${pct >= 80 ? "Great work — you're ready for this." : pct >= 50 ? "Good start. A few topics to tighten up." : "Worth another pass through these lectures."}</h3>
      <div class="hint">${wrong.length ? "Revise next — open an explanation in chat:" : "Try a harder set with more questions, or pick another week."}</div>
      ${wrong.length ? `<div class="chips">${wrong.map((x) => `<button class="chip" data-explain="${esc(x.concept)}">${esc(x.concept)}${x.week ? ` · W${x.week}` : ""}</button>`).join("")}</div>` : ""}
    </div></div>`;
}

// ------------------------------------------------------------------ course map
function renderWeeks() {
  const weeks = state.weeks.filter((w) => !state.courseId || w.course_id === state.courseId);
  const byCourse = {};
  weeks.forEach((w) => (byCourse[w.course_id] ||= []).push(w));
  $("#content").innerHTML = `<div class="page">
    <div class="page-head"><div class="ic ic-blue">${I.grid}</div><div><h2>Course map</h2><p>Every lecture you have notes for. Open a week for a recap, or quiz yourself on it.</p></div></div>
    ${Object.keys(byCourse).length ? Object.entries(byCourse).map(([cid, ws]) => `
      <div class="section-title">${esc(courseName(cid) || cid)}</div>
      <div class="weeks">${ws.map((w) => `<div class="card week">
        <span class="wk">Week ${w.week}</span><b>${esc(w.title || w.label)}</b>
        <div class="row"><button data-recap="${w.week}" data-c="${esc(cid)}">Recap</button><button data-wquiz="${w.week}" data-c="${esc(cid)}">Quiz me</button></div>
      </div>`).join("")}</div>`).join("") : `<div class="empty-state">No lecture notes yet for this course.</div>`}
  </div>`;
  document.querySelectorAll("[data-recap]").forEach((b) => (b.onclick = () => {
    state.courseId = b.dataset.c; state.chatId = null; ask(`What was covered in Week ${b.dataset.recap}?`);
  }));
  document.querySelectorAll("[data-wquiz]").forEach((b) => (b.onclick = () => {
    state.courseId = b.dataset.c; Object.assign(state.quizSetup, { mode: "week", week: b.dataset.wquiz });
    state.view = "brainstorm"; generateQuiz();
  }));
}

// ------------------------------------------------------------------ deadlines
function renderDeadlines() {
  const list = state.assignments.filter((a) => !state.courseId || a.course_id === state.courseId);
  const up = list.filter((a) => a.upcoming), past = list.filter((a) => !a.upcoming).slice(0, 12);
  const row = (a) => {
    const d = a.due_at ? new Date(a.due_at) : null;
    return `<div class="card dl">
      <div class="date ${a.upcoming ? "" : "past"}">${d ? `<b>${d.getDate()}</b><small>${d.toLocaleString(undefined, { month: "short" })}</small>` : "<small>No date</small>"}</div>
      <div class="info"><b>${esc(a.name)}</b><small>${esc(courseName(a.course_id))} · ${esc(fmtDue(a.due_at))}${a.points ? ` · ${a.points} pts` : ""}</small>
        ${a.upcoming ? `<div class="due">${esc(relDue(a.due_at))}</div>` : ""}</div>
      <div class="btns">
        ${a.linked_to_lectures && a.has_spec ? `<button class="btn btn-ghost" data-need="${esc(a.name)}" data-c="${esc(a.course_id)}">Lectures I need</button><button class="btn btn-ghost" data-aquiz="${esc(a.id)}" data-c="${esc(a.course_id)}">${I.spark} Quiz me</button>` : ""}
        ${a.html_url ? `<a class="btn btn-ghost" href="${esc(a.html_url)}" target="_blank" rel="noopener">Canvas ${I.ext}</a>` : ""}
      </div></div>`;
  };
  $("#content").innerHTML = `<div class="page">
    <div class="page-head"><div class="ic ic-amber">${I.cal}</div><div><h2>Deadlines</h2><p>From your Canvas courses. Plan the lectures you need, then quiz yourself.</p></div></div>
    <div class="section-title">Upcoming</div>
    ${up.length ? up.map(row).join("") : `<div class="empty-state">Nothing due right now.</div>`}
    ${past.length ? `<div class="section-title">Recently past</div>${past.map(row).join("")}` : ""}
  </div>`;
  document.querySelectorAll("[data-need]").forEach((b) => (b.onclick = () => {
    state.courseId = b.dataset.c; state.chatId = null; ask(`What lectures do I need for ${b.dataset.need}?`);
  }));
  document.querySelectorAll("[data-aquiz]").forEach((b) => (b.onclick = () => {
    state.courseId = b.dataset.c; Object.assign(state.quizSetup, { mode: "assignment", assignmentId: b.dataset.aquiz });
    state.view = "brainstorm"; generateQuiz();
  }));
}

// ------------------------------------------------------------------ start
if (state.session && state.session.exp > Date.now()) boot(); else render();
