/*
 * MOCK DATA
 * ---------
 * Subjects, weeks and Canvas materials now come from the backend (see api.service.ts).
 * What's left here is the scripted demo: AI students, the teaching conversation,
 * the Understanding Map and a few Home-page stats. Replace these as the AI backend grows.
 */
import { ChatMessage, Persona, PersonaId, Status, Subject } from './models';

export const CURRENT_WEEK = 6;

/** The account used by "Continue with Canvas" in the demo. */
export const DEMO_USER = { name: 'Riya Sharma', email: 'riya.sharma@uni.edu.au', via: 'canvas' as const };

/** Only used if the backend isn't running, and by the scripted demo. */
export const SUBJECTS: Subject[] = [
  {
    id: 'ds201',
    code: 'DS 201',
    name: 'Data Structures',
    badge: { label: 'Week 6 new', tone: 'new' },
    materialsSummary: '1 lectorial · 1 slide deck · 2 readings',
    cta: 'Teach Week 6',
    progress: 'EEEGSNUUUUUU',
    topics: ['Arrays and complexity', 'Linked lists', 'Stacks and queues', 'Trees', 'Heaps and priority queues', 'Hash tables and collisions'],
  },
  {
    id: 'econ110',
    code: 'ECON 110',
    name: 'Microeconomics',
    badge: { label: 'Week 6 new', tone: 'new' },
    materialsSummary: '1 lectorial · 2 slide decks · 1 reading',
    cta: 'Teach Week 6',
    progress: 'EESEENUUUUUU',
    topics: ['Scarcity and choice', 'Supply and demand', 'Elasticity', 'Consumer choice', 'Costs of production', 'Perfect competition'],
  },
  {
    id: 'bio150',
    code: 'BIO 150',
    name: 'Human Biology',
    badge: { label: 'On track', tone: 'ok' },
    materialsSummary: '2 lectorials · 1 lab sheet · 1 reading',
    cta: 'Revise Weeks 1–5',
    progress: 'ESGSENUUUUUU',
    topics: ['Cells and tissues', 'Nervous system', 'Endocrine system', 'Cardiovascular system', 'Respiratory system', 'Digestive system'],
  },
];

export const STATUS_LABELS: Record<string, string> = {
  E: 'Explained well',
  S: 'Shaky',
  G: 'Gap found',
  N: 'Not taught yet',
  U: 'Upcoming',
};

export const STREAK = [
  { label: 'M', state: 'on' },
  { label: 'T', state: 'on' },
  { label: 'W', state: 'on' },
  { label: 'T', state: 'on' },
  { label: 'F', state: 'today' },
  { label: 'S', state: 'off' },
  { label: 'S', state: 'off' },
];

export const GAPS: { concept: string; subjectName: string; week: number; persona: PersonaId; status: Status }[] = [
  { concept: 'Deleting from a linked list', subjectName: 'Data Structures', week: 2, persona: 'milo', status: 'G' },
  { concept: 'Hormone feedback loops', subjectName: 'Human Biology', week: 3, persona: 'sage', status: 'G' },
  { concept: 'Price elasticity of demand', subjectName: 'Microeconomics', week: 3, persona: 'pip', status: 'S' },
];

export const PERSONAS: Record<PersonaId, Persona> = {
  pip: {
    id: 'pip',
    name: 'Pip',
    kind: 'the curious kid',
    desc: 'Needs it simple. Asks "but why?" until there\'s no jargon left.',
  },
  sage: {
    id: 'sage',
    name: 'Sage',
    kind: 'the sceptic',
    desc: 'Won\'t accept "it just works". Wants examples and proof.',
  },
  milo: {
    id: 'milo',
    name: 'Milo',
    kind: 'the mixed-up one',
    desc: 'Already believes something wrong. You have to talk him out of it.',
  },
};

/* ---------- Teaching session (scripted demo for DS 201 · Week 6) ---------- */

export const SESSION_IDEAS = [
  { name: 'Hash functions', state: 'E' },
  { name: 'Collisions', state: 'current' },
  { name: 'Load factor', state: 'S' },
  { name: 'Chaining', state: 'todo' },
  { name: 'Open addressing', state: 'todo' },
  { name: 'Rehashing', state: 'todo' },
];

export const DEMO_CONVERSATION: ChatMessage[] = [
  { from: 'student', text: 'Okay so a hash table is a row of boxes, and the hash function tells me which box to put stuff in. I think I get that bit!' },
  { from: 'me', via: 'voice', meta: 'You, out loud · 0:14', text: "Right, and it's fast because you jump straight to the right box instead of searching through everything." },
  { from: 'student', text: 'Ooh. But what if two different things get sent to the SAME box? Does the new one just kick the old one out?' },
  { from: 'me', via: 'voice', meta: 'You, out loud · 0:09', text: "No, um… it goes in the next box? Or there's a list? Both, I think." },
  { type: 'flag', text: '{name} spotted something vague: two methods mixed together' },
  { from: 'student', text: "Both?? Now I'm more confused. Is it the next box or a list? Are those two different ways of doing it?" },
];

/** Shown as a live transcription bubble while the mic is on. */
export const LIVE_DRAFT = 'Yes! So there are two ways. One is called chaining, where each box keeps a little list…';

export const SLIDE_HINT = 'Slide 14: chaining keeps a list in each box; open addressing looks for the next free box.';

/** Canned replies when you type. Replace with a call to your LLM backend. */
export const PERSONA_REPLIES: Record<PersonaId, string[]> = {
  pip: [
    'Ohhh, a little list in each box! But then how do I find my thing again if the list gets really long?',
    'Wait, so if the boxes fill up, what happens? Do we just get more boxes?',
    'Ohhh, now I get it! Can I try explaining it back to you?',
  ],
  sage: [
    'Fine, but give me an example. Two real keys that would land in the same box.',
    "You keep saying it's fast. Fast compared to what, and when does that stop being true?",
    'Alright. That actually holds up. I believe you now.',
  ],
  milo: [
    'But I thought a good hash function means collisions never happen at all?',
    'Hmm, so collisions are normal? I was sure they meant the table was broken.',
    'Oh. So I had it backwards the whole time. That makes way more sense.',
  ],
};

export const NOTEBOOK = [
  { text: 'hash table = a row of boxes' },
  { text: 'hash function picks the box → super fast' },
  { text: 'same box?? next box OR a list?? ask again!', warn: true },
];

/* ---------- Understanding Map ---------- */

export const MAP_ROOT = { title: 'Hash tables', sub: 'Week 6 topic', x: 355, y: 0 };

export const MAP_NODES: { id: string; title: string; status: Status; x: number; y: number; note: string; time: string | null }[] = [
  { id: 'hf', title: 'Hash functions', status: 'E', x: 25, y: 150, note: 'Clear and simple. You used the "row of boxes" picture and Pip got it first time.', time: '01:12' },
  { id: 'col', title: 'Collisions', status: 'S', x: 355, y: 150, note: 'You knew collisions happen but mixed up the two ways of handling them.', time: '05:31' },
  { id: 'lf', title: 'Load factor', status: 'S', x: 685, y: 150, note: "You described it as the table's size. It's how full the table is.", time: '14:05' },
  { id: 'ch', title: 'Chaining', status: 'E', x: 245, y: 300, note: 'Once you separated it from open addressing, your explanation was spot on.', time: '07:48' },
  { id: 'oa', title: 'Open addressing', status: 'G', x: 465, y: 300, note: "You couldn't say what happens when the next box is full too, or how to find the item later.", time: '09:42' },
  { id: 'rh', title: 'Rehashing', status: 'N', x: 685, y: 300, note: "This didn't come up. It's on the Week 6 slides, so it may be on the quiz.", time: null },
];

/** Connector lines for the map tree: [left, top, width, height] in px. */
export const MAP_LINES: [number, number, number, number][] = [
  [449, 64, 2, 46],
  [120, 110, 662, 2],
  [119, 110, 2, 40],
  [449, 110, 2, 40],
  [779, 110, 2, 40],
  [449, 220, 2, 42],
  [340, 262, 222, 2],
  [339, 262, 2, 38],
  [559, 262, 2, 38],
  [779, 220, 2, 80],
];

export const MAP_ISSUES: { status: Status; title: string; text: string; time: string }[] = [
  {
    status: 'G',
    title: 'Open addressing',
    text: 'You said items go "in the next box" but couldn\'t say what happens when that box is full too, or how you\'d find the item again later.',
    time: '09:42',
  },
  {
    status: 'S',
    title: 'Load factor',
    text: "You described it as the size of the table. It's how full the table is, which is why it decides when to resize.",
    time: '14:05',
  },
];

export const TOUGHEST_QUESTION = '"If you delete something from the middle, how do you find the things after it?"';

export const SEMESTER = 'EEEGSTUUUUUU';
