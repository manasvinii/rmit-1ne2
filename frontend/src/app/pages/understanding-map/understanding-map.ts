import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Location } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';
import { MAP_ISSUES, MAP_LINES, MAP_NODES, MAP_ROOT, PERSONAS, SEMESTER, TOUGHEST_QUESTION } from '../../core/mock-data';
import { MapNode, PersonaId, Status, UnderstandingMapData } from '../../core/models';
import { Avatar } from '../../shared/avatar/avatar';
import { Icon } from '../../shared/icon/icon';
import { StatusIcon } from '../../shared/status-icon/status-icon';

const NODE_STATE: Record<string, string> = {
  E: 'Explained well',
  S: 'Shaky',
  G: "Couldn't explain",
  N: "Didn't come up",
};

const SEM_LABELS: Record<string, string> = { E: 'Solid', S: 'Shaky', G: 'Gap', T: 'Today', U: 'Soon', N: 'Not taught' };

/* Tree geometry (matches .tree / .node in styles.css) */
const NODE_W = 190;
const NODE_H = 70;
const ROOT_H = 64;
const SLOT = 220;
const MIN_W = 900;
const ROW_Y = [0, 150, 300];

type Line = [number, number, number, number];
interface PlacedNode {
  id: string;
  title: string;
  status: Exclude<Status, 'T' | 'U'>;
  x: number;
  y: number;
  note: string;
  time: string | null;
  source?: MapNode['source'];
}
interface Layout {
  width: number;
  height: number;
  root: { title: string; sub: string; x: number; y: number };
  nodes: PlacedNode[];
  lines: Line[];
}

/** Root on top, ideas underneath, sub-ideas under their parent idea; connectors drawn as thin boxes. */
function layoutTree(data: UnderstandingMapData): Layout {
  const ids = new Set(data.nodes.map((n) => n.id));
  const tops = data.nodes.filter((n) => !n.parent || !ids.has(n.parent));
  const kids = (id: string) => data.nodes.filter((n) => n.parent === id);
  const slots = tops.reduce((sum, t) => sum + Math.max(1, kids(t.id).length), 0);
  const width = Math.max(MIN_W, slots * SLOT);
  const offset = (width - slots * SLOT) / 2;
  const hasLevel2 = tops.some((t) => kids(t.id).length);

  const nodes: PlacedNode[] = [];
  const lines: Line[] = [];
  const place = (n: MapNode, cx: number, row: number) =>
    nodes.push({ id: n.id, title: n.title, status: n.status, x: cx - NODE_W / 2, y: ROW_Y[row], note: n.note, time: n.time, source: n.source });

  const rootX = width / 2;
  const centres: number[] = [];
  let slot = 0;
  for (const t of tops) {
    const children = kids(t.id);
    const span = Math.max(1, children.length);
    const cx = offset + (slot + span / 2) * SLOT;
    centres.push(cx);
    place(t, cx, 1);
    const childCentres = children.map((_, i) => offset + (slot + i + 0.5) * SLOT);
    children.forEach((c, i) => place(c, childCentres[i], 2));
    if (children.length) {
      const top = ROW_Y[1] + NODE_H;
      const bar = ROW_Y[2] - 38;
      if (children.length === 1 && Math.abs(childCentres[0] - cx) < 2) {
        lines.push([cx - 1, top, 2, ROW_Y[2] - top]);
      } else {
        lines.push([cx - 1, top, 2, bar - top]);
        const l = Math.min(cx, ...childCentres);
        const r = Math.max(cx, ...childCentres);
        lines.push([l - 1, bar, r - l + 2, 2]);
        childCentres.forEach((x) => lines.push([x - 1, bar, 2, ROW_Y[2] - bar]));
      }
    }
    slot += span;
  }

  if (centres.length) {
    const bar = ROW_Y[1] - 40;
    lines.push([rootX - 1, ROOT_H, 2, bar - ROOT_H]);
    const l = Math.min(rootX, ...centres);
    const r = Math.max(rootX, ...centres);
    lines.push([l - 1, bar, r - l + 2, 2]);
    centres.forEach((x) => lines.push([x - 1, bar, 2, ROW_Y[1] - bar]));
  }

  return {
    width,
    height: (hasLevel2 ? ROW_Y[2] : ROW_Y[1]) + NODE_H + 2,
    root: { ...data.root, x: rootX - NODE_W / 2, y: 0 },
    nodes,
    lines,
  };
}

const DEMO_LAYOUT: Layout = {
  width: MIN_W,
  height: 372,
  root: MAP_ROOT,
  nodes: MAP_NODES as PlacedNode[],
  lines: MAP_LINES,
};

@Component({
  selector: 'app-understanding-map',
  imports: [RouterLink, Icon, Avatar, StatusIcon],
  templateUrl: './understanding-map.html',
  styleUrl: './understanding-map.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UnderstandingMap {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly location = inject(Location);

  private readonly navState = history.state || {};
  private readonly sessionId: string | null =
    this.navState.sessionId || inject(ActivatedRoute).snapshot.queryParamMap.get('session');
  protected readonly demo = !this.sessionId;

  protected readonly data = signal<UnderstandingMapData | null>(null);
  protected readonly loading = signal(!this.demo);
  protected readonly error = signal('');
  protected readonly starting = signal<'reteach' | 'other' | null>(null);
  protected readonly nodeState = NODE_STATE;

  protected readonly persona = computed(
    () => PERSONAS[(this.data()?.persona || (this.navState.persona as PersonaId)) ?? 'pip'] || PERSONAS.pip,
  );
  protected readonly layout = computed<Layout | null>(() => {
    if (this.demo) return DEMO_LAYOUT;
    const d = this.data();
    return d ? layoutTree(d) : null;
  });
  protected readonly subjectName = computed(() => (this.demo ? 'Data Structures' : this.data()?.subject.name || ''));
  protected readonly lede = computed(() => {
    if (this.demo) return 'Data Structures · Week 6 · Hash tables and collisions';
    const d = this.data();
    if (!d) return '';
    return d.weeks.length === 1 ? `${d.subject.name} · ${d.weeksLabel} · ${d.topic}` : `${d.subject.name} · ${d.weeksLabel}`;
  });
  protected readonly minutes = computed(() => (this.demo ? 18 : this.data()?.minutes || 0));
  protected readonly issues = computed(() =>
    this.demo ? MAP_ISSUES.map((i) => ({ ...i, source: null as MapNode['source'] })) : this.data()?.issues || [],
  );
  protected readonly toughestQuestion = computed(() => (this.demo ? TOUGHEST_QUESTION : this.data()?.toughestQuestion));
  protected readonly semester = computed(() =>
    (this.demo ? SEMESTER : this.data()?.semester || '').split('').map((c) => ({ c, label: SEM_LABELS[c] || '' })),
  );
  protected readonly upcoming = computed(() => {
    const s = this.semester();
    const first = s.findIndex((c) => c.c === 'U');
    return first < 0 ? null : first + 1 === s.length ? `Week ${s.length}` : `Weeks ${first + 1}–${s.length}`;
  });

  protected readonly selectedId = signal<string | null>(this.demo ? 'oa' : null);
  protected readonly selected = computed(() => {
    const nodes = this.layout()?.nodes || [];
    return nodes.find((n) => n.id === this.selectedId()) || null;
  });

  /** Demo counts the root as an idea; real maps count only the session's ideas. */
  protected readonly landed = computed(() =>
    this.demo ? MAP_NODES.filter((n) => n.status === 'E').length + 1 : this.data()?.landed || 0,
  );
  protected readonly total = computed(() => (this.demo ? MAP_NODES.length + 1 : this.data()?.total || 0));
  protected readonly scoreBar = computed(() => {
    const nodes = this.layout()?.nodes || [];
    const bar = (['E', 'S', 'G', 'N'] as const).flatMap((s) => nodes.filter((n) => n.status === s).map(() => s as string));
    return this.demo ? ['E', ...bar] : bar;
  });
  protected readonly weakCount = computed(() => (this.layout()?.nodes || []).filter((n) => n.status === 'G' || n.status === 'S').length);

  constructor() {
    if (this.sessionId) {
      this.api.getMap(this.sessionId).subscribe({
        next: (d) => {
          this.data.set(d);
          this.location.replaceState('/map', `session=${d.sessionId}`);
          this.selectedId.set(d.issues[0] ? d.nodes.find((n) => n.title === d.issues[0].title)?.id || null : d.nodes[0]?.id || null);
          this.loading.set(false);
        },
        error: (e: Error) => {
          this.error.set(e.message);
          this.loading.set(false);
        },
      });
    }
  }

  protected link(url: string | null | undefined): string | null {
    return this.api.absoluteUrl(url);
  }

  /** Milo by default; if Milo was the student already, Sage. */
  protected readonly otherPersona = computed(() => (this.persona().id === 'milo' ? PERSONAS.sage : PERSONAS.milo));

  /** Re-teach the weak spots (same student), or everything to another student. */
  protected again(kind: 'reteach' | 'other'): void {
    const other = this.otherPersona().id;
    if (this.demo || !this.sessionId) {
      this.router.navigate([kind === 'other' ? '/setup' : '/session'], { state: { persona: kind === 'other' ? other : this.persona().id } });
      return;
    }
    if (this.starting()) return;
    this.starting.set(kind);
    this.api.reteach(this.sessionId, kind === 'other' ? other : undefined).subscribe({
      next: (s) => this.router.navigate(['/session'], { queryParams: { id: s.id } }),
      error: (e: Error) => {
        this.starting.set(null);
        this.error.set(e.message);
      },
    });
  }
}
