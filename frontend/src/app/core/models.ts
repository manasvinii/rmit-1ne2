/*
 * Shapes shared by the pages and the backend API.
 *
 * Week status codes used throughout:
 *   E = explained well   S = shaky   G = gap found
 *   N = released but not taught yet   U = upcoming (not on Canvas yet)
 *   T = today's session (semester strip only)
 */

export type PersonaId = 'pip' | 'sage' | 'milo';
export type Status = 'E' | 'S' | 'G' | 'N' | 'U' | 'T';
export type MaterialKind = 'video' | 'slides' | 'reading' | 'file';
/** single = one week, range = weeks 1..N, pick = any combination of weeks */
export type Mode = 'single' | 'range' | 'pick';

export interface User {
  name: string;
  email: string;
  via: 'canvas' | 'email';
}

/** Signed-in session kept in localStorage: the backend-issued token, never a Canvas token. */
export interface AuthSession {
  user: User;
  token: string;
  expiresAt: number; // ms since epoch
}

export interface Subject {
  id: string;
  code: string;
  name: string;
  badge: { label: string; tone: 'new' | 'ok' };
  materialsSummary: string;
  cta: string;
  progress: string; // one status letter per week, e.g. "EEESNUUUUUUU"
  topics: string[]; // topic per week
  currentWeek?: number;
  totalWeeks?: number;
  weeksWithMaterial?: number[];
  term?: string | null;
  canvasUrl?: string;
}

export interface SubjectsResponse {
  currentWeek: number;
  totalWeeks: number;
  subjects: Subject[];
  skippedCourses?: string[];
}

export interface Material {
  id: string;
  kind: MaterialKind;
  title: string;
  sub: string;
  off?: boolean; // unticked by default (tutorial sheets etc.)
  week?: number;
  items?: string[]; // several weeks: the materials this summary row stands for
  source?: { type: 'page' | 'file' | 'video' | 'link'; url?: string | null; [key: string]: unknown };
}

export interface Persona {
  id: PersonaId;
  name: string;
  kind: string;
  desc: string;
}

/** What Setup hands to the teaching session (router state). */
export interface SessionState {
  subjectId?: string;
  subject?: Pick<Subject, 'id' | 'code' | 'name' | 'topics'>;
  week?: number;
  weeks?: number[]; // the exact weeks chosen (any combination)
  mode?: Mode;
  persona?: PersonaId;
  input?: 'voice' | 'text';
  length?: number;
  exclude?: string[];
  include?: string[];
  materials?: Material[];
}

export interface ChatMessage {
  from?: 'student' | 'me';
  type?: 'flag' | 'hint';
  via?: 'voice' | 'text';
  meta?: string;
  text: string;
}

/* ---------- Teaching sessions (backend: /api/sessions) ---------- */

export interface SessionIdea {
  id: string;
  name: string;
  week: number;
  state: 'current' | 'todo' | 'E' | 'S' | 'G';
}

export interface SourceCard {
  title: string;
  resource: string;
  url: string | null;
  video: { label: string; url: string | null } | null;
}

export interface TeachingSession {
  id: string;
  persona: PersonaId;
  subject: Pick<Subject, 'id' | 'code' | 'name' | 'topics'>;
  weeks: number[];
  weeksLabel: string;
  topic: string;
  ideas: SessionIdea[];
  current: string | null;
  confusion: number; // 0..5
  confusionLabel: string;
  notebook: { text: string; warn: boolean }[];
  messages: ChatMessage[];
  source: SourceCard | null;
  complete: boolean;
  secondsTotal: number;
  elapsed: number;
  ended: boolean;
  input: 'voice' | 'text';
  method?: 'llm' | 'rules';
}

export interface MapNode {
  id: string;
  title: string;
  week: number;
  status: 'E' | 'S' | 'G' | 'N';
  note: string;
  time: string | null;
  parent: string | null;
  source: { label: string; url: string | null } | null;
}

export interface UnderstandingMapData {
  sessionId: string;
  persona: PersonaId;
  courseId: string;
  weeks: number[];
  weeksLabel: string;
  topic: string;
  root: { title: string; sub: string };
  nodes: MapNode[];
  issues: { status: 'G' | 'S'; title: string; text: string; time: string; source: MapNode['source'] }[];
  toughestQuestion: string | null;
  landed: number;
  total: number;
  minutes: number;
  weakSpots: string[];
  semester: string;
  subject: { id: string; name: string; code: string };
}

export interface Gap {
  concept: string;
  subjectId: string;
  subjectName: string;
  week: number;
  persona: PersonaId;
  status: Status;
}

export interface SessionSummary {
  id: string;
  subjectId: string;
  persona: PersonaId;
  weeks: number[];
  startedAt: string;
  endedAt: string | null;
  landed: number | null;
  total: number | null;
}

/* ---------- Ask Pupil chatbot (backend: POST /query) ---------- */

export type ChatRoute = 'STRUCTURED_CANVAS' | 'VECTOR_RAG' | 'GRAPH' | 'GRAPH_VECTOR';

export interface ChatSource {
  id: string; // citation marker used in the reply, e.g. "S1"
  type: 'pdf' | 'slides' | 'video' | 'canvas' | 'graph';
  title: string;
  course_id?: string | null;
  week?: number | null;
  module?: string | null;
  page?: number | null;
  page_end?: number | null;
  timestamp?: string | null;
  url?: string | null;
  snippet?: string | null;
  support: 'direct' | 'inferred';
  relation?: string | null;
  aligned_slide?: string | null;
}

export interface ChatAnswer {
  reply: string;
  sources: ChatSource[];
  route: ChatRoute;
  confidence: number;
  intent?: string | null;
  notes: string[];
}

export interface Assignment {
  id: string;
  name: string;
  course_id: string;
  course_name: string;
  due_at: string | null;
  upcoming: boolean;
  html_url: string | null;
}
