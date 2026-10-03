import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { catchError, of, switchMap } from 'rxjs';
import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { CURRENT_WEEK, GAPS, PERSONAS, STATUS_LABELS, STREAK, SUBJECTS } from '../../core/mock-data';
import { Assignment, Gap, SessionState, SessionSummary, Subject } from '../../core/models';
import { Avatar } from '../../shared/avatar/avatar';
import { Icon } from '../../shared/icon/icon';
import { StatusIcon } from '../../shared/status-icon/status-icon';

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

const DAY_LETTERS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

@Component({
  selector: 'app-home',
  imports: [RouterLink, Icon, Avatar, StatusIcon],
  templateUrl: './home.html',
  styleUrl: './home.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Home {
  private readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);

  protected readonly greeting = greeting();
  protected readonly firstName = computed(() => this.auth.user()?.name?.split(' ')[0] || 'there');
  protected readonly profileLabel = computed(() => `${this.auth.user()?.name || 'Your'}'s profile`);

  // Subjects come from Canvas via the backend; the mock ones are shown if it's not running.
  protected readonly subjects = signal<Subject[] | null>(null);
  protected readonly currentWeek = signal(CURRENT_WEEK);
  protected readonly usingMock = signal(false);
  private readonly sessions = signal<SessionSummary[]>([]);
  private readonly assignments = signal<Assignment[]>([]);
  private readonly liveGaps = signal<Gap[] | null>(null);

  protected readonly personas = PERSONAS;
  protected readonly statusLabels = STATUS_LABELS;
  protected readonly how = [
    ['Pick a week', 'Lectorials, slides and readings come straight from Canvas.'],
    ['Teach a confused student', "Explain it out loud. They push back where you're vague."],
    ['See your map', 'Find out what you really understand before the exam does.'],
  ];

  protected readonly syncState = signal<'idle' | 'syncing' | 'done'>('idle');
  protected readonly syncError = signal('');

  // ---- hero: the first subject's current week
  protected readonly heroSubject = computed(() => this.subjects()?.[0] || null);
  protected readonly heroWeek = computed(() => this.heroSubject()?.currentWeek ?? this.currentWeek());
  protected readonly heroTopic = computed(() => this.heroSubject()?.topics[this.heroWeek() - 1] || `Week ${this.heroWeek()}`);

  // ---- stats
  protected readonly streak = computed(() => {
    if (this.usingMock()) return { days: 5, week: STREAK };
    const taught = new Set(this.sessions().map((s) => dayKey(new Date(s.startedAt))));
    const today = new Date();
    const week = Array.from({ length: 7 }, (_, i) => {
      const d = new Date(today);
      d.setDate(today.getDate() - (6 - i));
      const state = i === 6 ? 'today' : taught.has(dayKey(d)) ? 'on' : 'off';
      return { label: DAY_LETTERS[d.getDay()], state };
    });
    let days = 0;
    const d = new Date(today);
    if (!taught.has(dayKey(d))) d.setDate(d.getDate() - 1); // today not taught yet doesn't break the streak
    while (taught.has(dayKey(d))) {
      days++;
      d.setDate(d.getDate() - 1);
    }
    return { days, week };
  });
  protected readonly explained = computed(() => {
    if (this.usingMock()) return { landed: 34, total: 58 };
    const done = this.sessions().filter((s) => s.total);
    return { landed: done.reduce((n, s) => n + (s.landed || 0), 0), total: done.reduce((n, s) => n + (s.total || 0), 0) };
  });
  protected readonly nextDue = computed(() => {
    if (this.usingMock()) return { title: 'Quiz 3 on Thursday', sub: 'Covers Weeks 4–6 · from Canvas' };
    const a = this.assignments().find((x) => x.upcoming && x.due_at);
    if (!a) return null;
    const due = new Date(a.due_at!);
    const when = due.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' });
    return { title: `${a.name}`, sub: `Due ${when} · ${a.course_name || 'from Canvas'}` };
  });
  protected readonly gaps = computed(() => (this.usingMock() ? (GAPS as Gap[]) : this.liveGaps() || []));

  constructor() {
    this.load(false);
  }

  private load(refresh: boolean): void {
    this.api.getSubjects(refresh).subscribe({
      next: (r) => {
        this.subjects.set(r.subjects);
        this.currentWeek.set(r.currentWeek);
        this.usingMock.set(false);
        if (refresh) this.syncState.set('done');
        this.loadActivity();
      },
      error: () => {
        this.subjects.set(SUBJECTS);
        this.usingMock.set(true);
        if (refresh) this.syncState.set('idle');
      },
    });
  }

  private loadActivity(): void {
    this.api.listSessions().subscribe({ next: (s) => this.sessions.set(s), error: () => this.sessions.set([]) });
    this.api.getGaps().subscribe({ next: (g) => this.liveGaps.set(g), error: () => this.liveGaps.set([]) });
    this.api.getAssignments().subscribe({ next: (a) => this.assignments.set(a), error: () => this.assignments.set([]) });
  }

  /** "Sync from Canvas": pull courses and assignments with the stored token, then reload subjects. */
  protected sync(): void {
    this.syncState.set('syncing');
    this.syncError.set('');
    this.api
      .syncCanvas()
      .pipe(
        catchError((e: Error) => {
          this.syncError.set(e.message);
          return of(null);
        }),
        switchMap(() => this.api.getSubjects(true)),
      )
      .subscribe({
        next: (r) => {
          this.subjects.set(r.subjects);
          this.currentWeek.set(r.currentWeek);
          this.usingMock.set(false);
          this.syncState.set(this.syncError() ? 'idle' : 'done');
          this.auth.refreshProfile();
          this.loadActivity();
        },
        error: () => this.syncState.set('idle'),
      });
  }

  /** Router state for the Setup page, so it opens on this subject and week. */
  protected setupState(s: Subject, mode?: 'single' | 'range'): SessionState {
    return { subjectId: s.id, week: s.currentWeek ?? this.currentWeek(), mode: mode || (s.badge.tone === 'ok' ? 'range' : 'single') };
  }

  protected gapState(g: Gap): SessionState {
    return { subjectId: g.subjectId, week: g.week, mode: 'single', persona: g.persona };
  }

  protected weeks(progress: string): string[] {
    return progress.split('');
  }
}
