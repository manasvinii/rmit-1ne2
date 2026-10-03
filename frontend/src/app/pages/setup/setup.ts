import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { API_BASE, ApiService, WeekScope } from '../../core/api.service';
import { PERSONAS } from '../../core/mock-data';
import { Material, Mode, PersonaId, SessionState, Subject } from '../../core/models';
import { Avatar } from '../../shared/avatar/avatar';
import { Icon } from '../../shared/icon/icon';

const MATERIAL_ICONS: Record<string, { icon: string; tone: string }> = {
  video: { icon: 'video', tone: 'violet' },
  slides: { icon: 'slides', tone: 'amber' },
  reading: { icon: 'book', tone: 'teal' },
  file: { icon: 'file', tone: 'grey' },
};

function weeksLabel(ws: number[]): string {
  if (ws.length === 1) return `Week ${ws[0]}`;
  const contiguous = ws.every((w, i) => i === 0 || w === ws[i - 1] + 1);
  return contiguous ? `Weeks ${ws[0]}–${ws[ws.length - 1]}` : `Weeks ${ws.join(', ')}`;
}

@Component({
  selector: 'app-setup',
  imports: [RouterLink, Icon, Avatar],
  templateUrl: './setup.html',
  styleUrl: './setup.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Setup {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  protected readonly apiBase = API_BASE;
  protected readonly personaList = Object.values(PERSONAS);
  protected readonly personas = PERSONAS;
  protected readonly lengths = [10, 15, 25];

  // ---- subjects from Canvas (via the backend)
  protected readonly subjects = signal<Subject[] | null>(null);
  protected readonly subjectsError = signal('');

  // ---- choices (may arrive from Home via router state)
  private readonly initial: SessionState & { subjectId?: string } = history.state || {};
  protected readonly subjectId = signal<string | null>(this.initial.subjectId || null);
  protected readonly mode = signal<Mode>(this.initial.mode || 'single');
  protected readonly week = signal<number | null>(this.initial.week || null);
  /** Pick mode: any combination of weeks */
  protected readonly picked = signal<number[]>(this.initial.weeks || []);
  protected readonly persona = signal<PersonaId>(this.initial.persona || 'pip');
  protected readonly input = signal<'voice' | 'text'>('voice');
  protected readonly length = signal(15);
  /** material id -> true when unticked (or false when an off-by-default one is ticked) */
  protected readonly excluded = signal<Record<string, boolean>>({});

  // ---- materials for the chosen week(s)
  protected readonly materials = signal<Material[]>([]);
  protected readonly materialsLoading = signal(false);
  protected readonly materialsError = signal('');
  private materialsSub?: Subscription;

  // ---- derived values used by the template
  protected readonly subject = computed(() => {
    const list = this.subjects() || [];
    return list.find((s) => s.id === this.subjectId()) || list[0] || null;
  });
  protected readonly totalWeeks = computed(() => this.subject()?.totalWeeks ?? 12);
  protected readonly currentWeek = computed(() => this.subject()?.currentWeek ?? 1);
  protected readonly weekNumbers = computed(() => Array.from({ length: this.totalWeeks() }, (_, i) => i + 1));
  protected readonly includedCount = computed(() => this.materials().filter((m) => this.isIncluded(m)).length);

  /** The weeks the session will cover, whatever the mode. */
  protected readonly chosenWeeks = computed<number[]>(() => {
    const w = this.week() ?? 1;
    if (this.mode() === 'pick') return this.picked().length ? [...this.picked()].sort((a, b) => a - b) : [w];
    if (this.mode() === 'range') return Array.from({ length: w }, (_, i) => i + 1);
    return [w];
  });
  protected readonly isRange = computed(() => this.chosenWeeks().length > 1);
  private readonly scope = computed<WeekScope>(() => ({ week: this.week() ?? 1, mode: this.mode(), weeks: this.chosenWeeks() }));

  protected readonly ideas = computed(() => {
    const s = this.subject();
    if (!s) return [];
    return this.chosenWeeks()
      .map((n) => this.topicFor(n))
      .filter((t) => !/^Week \d+$/.test(t));
  });

  protected readonly rangeLabel = computed(() => {
    const ws = this.chosenWeeks();
    if (ws.length === 1) return `Week ${ws[0]} · ${this.topicFor(ws[0])}`;
    return `${weeksLabel(ws)} · mixed revision across ${ws.length} weeks of material`;
  });

  constructor() {
    this.loadSubjects();

    // Reload materials whenever subject or chosen weeks change.
    effect(() => {
      const s = this.subject();
      const scope = this.scope();
      if (!s || !this.week()) return;
      this.materialsSub?.unsubscribe();
      this.materialsLoading.set(true);
      this.materialsError.set('');
      this.materialsSub = this.api.getMaterials(s.id, scope).subscribe({
        next: (list) => {
          this.materials.set(list);
          this.materialsLoading.set(false);
        },
        error: (e: Error) => {
          this.materials.set([]);
          this.materialsError.set(e.message);
          this.materialsLoading.set(false);
        },
      });
    });

    inject(DestroyRef).onDestroy(() => this.materialsSub?.unsubscribe());
  }

  protected loadSubjects(): void {
    this.subjectsError.set('');
    this.api.getSubjects().subscribe({
      next: (data) => {
        this.subjects.set(data.subjects);
        // Pick a real subject even if we came from a link with an unknown id.
        const match = data.subjects.find((s) => s.id === this.subjectId());
        const first = match || data.subjects[0];
        if (first) {
          const w = this.week();
          this.subjectId.set(first.id);
          this.week.set(w && w <= (first.currentWeek ?? 1) ? w : (first.currentWeek ?? 1));
          if (this.mode() === 'pick' && !this.picked().length) this.picked.set([this.week()!]);
        }
      },
      error: (e: Error) => this.subjectsError.set(e.message),
    });
  }

  // ---- template helpers
  protected topicFor(n: number): string {
    return this.subject()?.topics[n - 1] || `Week ${n}`;
  }

  protected hasMaterial(n: number): boolean {
    const ws = this.subject()?.weeksWithMaterial;
    return !ws || ws.includes(n);
  }

  protected isChosen(n: number): boolean {
    return this.mode() === 'pick' ? this.picked().includes(n) : n === this.week();
  }

  protected isIncluded(m: Material): boolean {
    const ex = this.excluded();
    return m.id in ex ? !ex[m.id] : !m.off;
  }

  protected toggle(m: Material): void {
    const included = this.isIncluded(m);
    this.excluded.update((ex) => ({ ...ex, [m.id]: included }));
  }

  protected icon(m: Material) {
    return MATERIAL_ICONS[m.kind] || MATERIAL_ICONS['file'];
  }

  protected link(m: Material): string | null {
    return this.api.materialLink(m);
  }

  private ticks() {
    const materials = this.materials();
    return {
      exclude: materials.filter((m) => !m.off && !this.isIncluded(m)).map((m) => m.id),
      include: materials.filter((m) => m.off && this.isIncluded(m)).map((m) => m.id),
    };
  }

  protected downloadAll(): void {
    const s = this.subject();
    if (s && this.week()) this.api.downloadZip(s.id, this.scope(), this.ticks());
  }

  protected setMode(m: Mode): void {
    this.mode.set(m);
    if (m === 'pick' && !this.picked().length && this.week()) this.picked.set([this.week()!]);
    this.excluded.set({});
  }

  protected chooseSubject(s: Subject): void {
    this.subjectId.set(s.id);
    this.week.set(s.currentWeek ?? 1);
    this.picked.set([s.currentWeek ?? 1]);
    this.excluded.set({});
  }

  protected chooseWeek(n: number): void {
    if (this.mode() === 'pick') {
      const cur = this.picked();
      const next = cur.includes(n) ? cur.filter((w) => w !== n) : [...cur, n];
      if (!next.length) return; // keep at least one week
      this.picked.set(next);
      this.week.set(Math.max(...next));
    } else {
      this.week.set(n);
    }
    this.excluded.set({});
  }

  protected start(): void {
    const s = this.subject();
    if (!s) return;
    // What the AI student may learn from: the chosen weeks and the ticked materials
    const state: SessionState = {
      subjectId: s.id,
      subject: { id: s.id, code: s.code, name: s.name, topics: s.topics },
      week: this.week()!,
      weeks: this.chosenWeeks(),
      mode: this.mode(),
      persona: this.persona(),
      input: this.input(),
      length: this.length(),
      ...this.ticks(),
      materials: this.materials().filter((m) => this.isIncluded(m)),
    };
    this.router.navigate(['/session'], { state });
  }
}
