import { ChangeDetectionStrategy, Component, ElementRef, afterRenderEffect, computed, inject, signal, viewChild } from '@angular/core';
import { ApiService } from '../../core/api.service';
import { ChatAnswer, ChatRoute, ChatSource, Subject } from '../../core/models';
import { Avatar } from '../../shared/avatar/avatar';
import { Icon } from '../../shared/icon/icon';

interface Turn {
  question: string;
  courseLabel: string;
  answer?: ChatAnswer;
  error?: string;
}

/** Reply text split into plain text and [S1]-style citation markers. */
type Part = { text: string } | { cite: string; source: ChatSource | undefined };

const STORAGE_KEY = 'pupil.ask';
const CITE = /\[([A-Z]\d+(?:\s*,\s*[A-Z]?\d+)*)\]/g;

type Tone = 'teal' | 'violet' | 'lime';

const ROUTE_LABEL: Record<ChatRoute, { label: string; icon: string; tone: Tone }> = {
  STRUCTURED_CANVAS: { label: 'From your Canvas data', icon: 'calendar', tone: 'teal' },
  VECTOR_RAG: { label: 'From lecture slides and recordings', icon: 'slides', tone: 'violet' },
  GRAPH: { label: 'From the course knowledge graph', icon: 'map', tone: 'lime' },
  GRAPH_VECTOR: { label: 'Knowledge graph + lecture evidence', icon: 'map', tone: 'lime' },
};

const SOURCE_ICON: Record<ChatSource['type'], string> = {
  pdf: 'file',
  slides: 'slides',
  video: 'video',
  canvas: 'calendar',
  graph: 'map',
};

const GROUPS: { title: string; blurb: string; icon: string; tone: Tone; questions: string[] }[] = [
  {
    title: 'Canvas',
    blurb: 'Deadlines, assessments and your courses',
    icon: 'calendar',
    tone: 'teal',
    questions: ['When is Assessment 2 due?', 'What assignments are due soon?'],
  },
  {
    title: 'Lectures',
    blurb: 'Explanations quoted from slides and recordings',
    icon: 'slides',
    tone: 'violet',
    questions: ['Explain gradient descent', 'Where did the lecturer talk about overfitting?'],
  },
  {
    title: 'Knowledge graph',
    blurb: 'What each week covers and what builds on what',
    icon: 'map',
    tone: 'lime',
    questions: ["What's new in week 6?", 'Which lectures do I need for Assessment 2?'],
  },
];

const PREVIEW_SOURCES = 3;

function loadTurns(): Turn[] {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]') as Turn[];
  } catch {
    return [];
  }
}

@Component({
  selector: 'app-ask',
  imports: [Icon, Avatar],
  templateUrl: './ask.html',
  styleUrl: './ask.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Ask {
  private readonly api = inject(ApiService);

  protected readonly groups = GROUPS;
  protected readonly previewCount = PREVIEW_SOURCES;
  protected readonly routeLabel = ROUTE_LABEL;
  protected readonly sourceIcon = SOURCE_ICON;

  protected readonly subjects = signal<Subject[]>([]);
  /** null = all my courses */
  protected readonly courseId = signal<string | null>(null);
  protected readonly turns = signal<Turn[]>(loadTurns());
  protected readonly draft = signal('');
  protected readonly asking = signal(false);
  protected readonly openSources = signal<Record<number, boolean>>({});

  protected readonly courseLabel = computed(() => {
    const s = this.subjects().find((x) => x.id === this.courseId());
    return s ? `${s.code} ${s.name}` : 'All my courses';
  });

  private readonly log = viewChild<ElementRef<HTMLElement>>('log');

  constructor() {
    this.api.getSubjects().subscribe({ next: (r) => this.subjects.set(r.subjects), error: () => this.subjects.set([]) });
    afterRenderEffect(() => {
      this.turns();
      this.asking();
      const el = this.log()?.nativeElement;
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    });
  }

  protected submit(event: Event): void {
    event.preventDefault();
    this.ask(this.draft());
  }

  protected ask(question: string): void {
    const q = question.trim();
    if (!q || this.asking()) return;
    this.draft.set('');
    this.asking.set(true);
    const index = this.turns().length;
    this.save([...this.turns(), { question: q, courseLabel: this.courseLabel() }]);
    this.api.ask(q, this.courseId()).subscribe({
      next: (answer) => this.finish(index, { answer }),
      error: (e: Error) => this.finish(index, { error: e.message }),
    });
  }

  private finish(index: number, patch: Partial<Turn>): void {
    this.save(this.turns().map((t, i) => (i === index ? { ...t, ...patch } : t)));
    this.asking.set(false);
  }

  private save(turns: Turn[]): void {
    this.turns.set(turns);
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(turns.slice(-30)));
    } catch {
      /* storage full or unavailable: keep the chat in memory only */
    }
  }

  protected clear(): void {
    this.save([]);
    this.openSources.set({});
  }

  protected toggleSources(i: number): void {
    this.openSources.update((o) => ({ ...o, [i]: !o[i] }));
  }

  protected visibleSources(answer: ChatAnswer, i: number): ChatSource[] {
    return this.openSources()[i] ? answer.sources : answer.sources.slice(0, PREVIEW_SOURCES);
  }

  /** Split the reply into text and citation chips that point at the matching source. */
  protected parts(answer: ChatAnswer): Part[] {
    const text = answer.reply.replace(/\\\(|\\\)/g, '');
    const byId = new Map(answer.sources.map((s) => [s.id, s]));
    const out: Part[] = [];
    let last = 0;
    for (const m of text.matchAll(CITE)) {
      if (m.index! > last) out.push({ text: text.slice(last, m.index) });
      let prefix = '';
      for (const raw of m[1].split(',')) {
        let id = raw.trim();
        prefix = id.match(/^[A-Z]/)?.[0] || prefix;
        if (!/^[A-Z]/.test(id)) id = prefix + id;
        out.push({ cite: id, source: byId.get(id) });
      }
      last = m.index! + m[0].length;
    }
    if (last < text.length) out.push({ text: text.slice(last) });
    return out;
  }

  protected isCite(p: Part): p is { cite: string; source: ChatSource | undefined } {
    return 'cite' in p;
  }

  protected location(s: ChatSource): string {
    const bits: string[] = [];
    if (s.week) bits.push(`Week ${s.week}`);
    if (s.timestamp) bits.push(s.timestamp);
    else if (s.page) bits.push(s.page_end && s.page_end !== s.page ? `Slides ${s.page}–${s.page_end}` : `Slide ${s.page}`);
    if (s.aligned_slide) bits.push(`matches ${s.aligned_slide}`);
    return bits.join(' · ');
  }

  protected link(s: ChatSource | undefined): string | null {
    return this.api.absoluteUrl(s?.url);
  }

  protected value(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }
}
