import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  afterRenderEffect,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { Location } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Observable } from 'rxjs';
import { ApiService } from '../../core/api.service';
import {
  CURRENT_WEEK,
  DEMO_CONVERSATION,
  LIVE_DRAFT,
  NOTEBOOK,
  PERSONAS,
  PERSONA_REPLIES,
  SESSION_IDEAS,
  SLIDE_HINT,
  SUBJECTS,
} from '../../core/mock-data';
import { ChatMessage, SessionIdea, SessionState, SourceCard, TeachingSession } from '../../core/models';
import { Avatar } from '../../shared/avatar/avatar';
import { Icon } from '../../shared/icon/icon';
import { StatusIcon } from '../../shared/status-icon/status-icon';

const WAVE = [6, 10, 16, 24, 14, 8, 18, 26, 20, 12, 6, 10, 22, 28, 18, 10, 14, 24, 16, 8, 6, 12, 20, 14, 10, 18, 26, 16, 8, 6, 10, 6];
/** Silence after the last spoken sentence before it is sent to the student. */
const VOICE_PAUSE_MS = 1800;

function formatTime(total: number): string {
  const m = Math.floor(total / 60);
  const s = String(total % 60).padStart(2, '0');
  return `${m}:${s}`;
}

/* Minimal typing for the Web Speech API (Chrome/Edge/Safari expose it with a webkit prefix). */
interface SpeechResultEvent {
  resultIndex: number;
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
}
interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((e: SpeechResultEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}
type SpeechCtor = new () => SpeechRecognitionLike;

@Component({
  selector: 'app-session',
  imports: [RouterLink, Icon, Avatar, StatusIcon],
  templateUrl: './session.html',
  styleUrl: './session.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Session implements OnDestroy {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly location = inject(Location);

  /** Choices from Setup (router state). Without them (and without ?id=) the scripted demo is shown. */
  private readonly state: SessionState = history.state || {};
  private readonly resumeId = inject(ActivatedRoute).snapshot.queryParamMap.get('id');
  protected readonly demo = !this.state.subjectId && !this.resumeId;

  // ---- live session from the backend
  protected readonly session = signal<TeachingSession | null>(null);
  protected readonly loading = signal(!this.demo);
  protected readonly error = signal('');
  protected readonly ending = signal(false);

  // ---- header
  private readonly demoSubject = SUBJECTS[0];
  protected readonly persona = computed(() => PERSONAS[this.session()?.persona || this.state.persona || 'pip']);
  protected readonly subjectName = computed(() => this.session()?.subject.name || this.state.subject?.name || this.demoSubject.name);
  protected readonly scopeLabel = computed(() => {
    const s = this.session();
    if (s) return !s.topic || s.topic === s.weeksLabel ? s.weeksLabel : `${s.weeksLabel} · ${s.topic}`;
    if (!this.demo) return 'Preparing…';
    return `Week ${CURRENT_WEEK} · ${this.demoSubject.topics[CURRENT_WEEK - 1]}`;
  });

  // ---- left / right panels
  protected readonly ideas = computed<Pick<SessionIdea, 'name' | 'state'>[]>(() =>
    this.demo ? (SESSION_IDEAS as Pick<SessionIdea, 'name' | 'state'>[]) : this.session()?.ideas || [],
  );
  protected readonly currentIdea = computed(() => this.ideas().find((i) => i.state === 'current')?.name || null);
  protected readonly source = computed<SourceCard | null>(() =>
    this.demo
      ? { title: 'Slide 14 · Handling collisions', resource: '', url: null, video: { label: 'Lectorial at 23:10', url: null } }
      : this.session()?.source || null,
  );
  protected readonly notebook = computed(() => (this.demo ? NOTEBOOK : this.session()?.notebook || []));
  protected readonly confusion = computed(() => (this.demo ? 3 : (this.session()?.confusion ?? 5)));
  protected readonly confusionLabel = computed(() => (this.demo ? 'Getting there' : this.session()?.confusionLabel || ''));
  protected readonly meter = [0, 1, 2, 3, 4];
  protected readonly complete = computed(() => !!this.session()?.complete);

  // ---- conversation
  protected readonly wave = WAVE.map((h, i) => ({ h, delay: (i % 8) * 90 }));
  protected readonly messages = signal<ChatMessage[]>(this.demo ? DEMO_CONVERSATION : []);
  protected readonly draft = signal('');
  protected readonly thinking = signal(false);
  protected readonly typingOpen = signal(this.state.input === 'text');

  // ---- voice
  private readonly SpeechRecognition: SpeechCtor | undefined =
    (window as unknown as { SpeechRecognition?: SpeechCtor; webkitSpeechRecognition?: SpeechCtor }).SpeechRecognition ||
    (window as unknown as { webkitSpeechRecognition?: SpeechCtor }).webkitSpeechRecognition;
  protected readonly voiceSupported = !!this.SpeechRecognition;
  protected readonly listening = signal(this.demo && this.state.input !== 'text');
  /** What is being said right now (interim + not yet sent). */
  protected readonly liveDraft = signal(this.demo ? LIVE_DRAFT : '');
  protected readonly voiceError = signal('');
  private recognition?: SpeechRecognitionLike;
  private spoken = '';
  private voiceTimer?: ReturnType<typeof setTimeout>;

  // ---- timer
  protected readonly secondsLeft = signal(Math.max((this.state.length || 15) * 60 - (this.demo ? 200 : 0), 60));
  protected readonly timeLeft = computed(() => formatTime(this.secondsLeft()));
  private readonly countdown = setInterval(() => this.secondsLeft.update((v) => Math.max(0, v - 1)), 1000);

  private readonly log = viewChild<ElementRef<HTMLElement>>('log');
  private replyIndex = 0;
  private timers: ReturnType<typeof setTimeout>[] = [];

  constructor() {
    afterRenderEffect(() => {
      this.messages();
      this.thinking();
      this.liveDraft();
      const el = this.log()?.nativeElement;
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    });
    if (!this.demo) this.load();
  }

  private load(): void {
    const s = this.state;
    const req: Observable<TeachingSession> = this.resumeId
      ? this.api.getSession(this.resumeId)
      : this.api.startSession({
          subjectId: s.subjectId!,
          week: s.week || 1,
          mode: s.mode || 'single',
          weeks: s.weeks,
          persona: s.persona || 'pip',
          input: s.input || 'voice',
          length: s.length || 15,
          exclude: s.exclude || [],
          include: s.include || [],
        });
    req.subscribe({
      next: (session) => {
        this.apply(session);
        this.loading.set(false);
        // So a reload resumes this session instead of starting a new one
        this.location.replaceState('/session', `id=${session.id}`);
        if (session.ended) this.router.navigate(['/map'], { state: { sessionId: session.id }, replaceUrl: true });
        else if (session.input !== 'text' && this.voiceSupported) this.startListening();
        else this.typingOpen.set(true);
      },
      error: (e: Error) => {
        this.error.set(e.message);
        this.loading.set(false);
      },
    });
  }

  private apply(session: TeachingSession): void {
    this.session.set(session);
    this.messages.set(session.messages);
    this.secondsLeft.set(Math.max(session.secondsTotal - session.elapsed, 0));
  }

  // ------------------------------------------------------------------ teaching
  protected send(event: Event): void {
    event.preventDefault();
    const text = this.draft().trim();
    if (!text || this.thinking()) return;
    this.draft.set('');
    this.teach(text, 'text');
  }

  private teach(text: string, via: 'voice' | 'text'): void {
    const meta = via === 'voice' ? 'You, out loud' : 'You, typed';
    this.messages.update((m) => [...m, { from: 'me', via, meta, text }]);
    this.thinking.set(true);

    if (this.demo) {
      const t = setTimeout(() => {
        const replies = PERSONA_REPLIES[this.persona().id];
        this.messages.update((m) => [...m, { from: 'student', text: replies[this.replyIndex++ % replies.length] }]);
        this.thinking.set(false);
      }, 1200);
      this.timers.push(t);
      return;
    }

    this.api.sendMessage(this.session()!.id, text, via).subscribe({
      next: (s) => {
        this.apply(s);
        this.thinking.set(false);
      },
      error: (e: Error) => {
        this.thinking.set(false);
        this.messages.update((m) => [...m, { type: 'hint', text: `Couldn't reach ${this.persona().name}: ${e.message}` }]);
      },
    });
  }

  protected showHint(): void {
    if (this.demo) {
      this.messages.update((m) => [...m, { type: 'hint', text: SLIDE_HINT }]);
      return;
    }
    const s = this.session();
    if (!s || this.thinking()) return;
    this.api.hint(s.id).subscribe({ next: (next) => this.apply(next) });
  }

  protected end(): void {
    if (this.demo) {
      this.router.navigate(['/map'], { state: { persona: this.persona().id } });
      return;
    }
    const s = this.session();
    if (!s || this.ending()) return;
    this.stopListening();
    this.ending.set(true);
    this.api.endSession(s.id).subscribe({
      next: () => this.router.navigate(['/map'], { state: { sessionId: s.id } }),
      error: (e: Error) => {
        this.ending.set(false);
        this.error.set(e.message);
      },
    });
  }

  // ------------------------------------------------------------------ voice
  protected toggleMic(): void {
    if (this.listening()) this.stopListening();
    else this.startListening();
  }

  private startListening(): void {
    if (this.demo) {
      this.listening.set(true);
      return;
    }
    if (!this.SpeechRecognition) {
      this.voiceError.set("This browser can't transcribe speech. Use Type instead (Chrome or Edge can).");
      this.typingOpen.set(true);
      return;
    }
    this.voiceError.set('');
    const rec = new this.SpeechRecognition();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = 'en-AU';
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) this.spoken += ' ' + r[0].transcript.trim();
        else interim += r[0].transcript;
      }
      this.liveDraft.set((this.spoken + ' ' + interim).trim());
      clearTimeout(this.voiceTimer);
      this.voiceTimer = setTimeout(() => this.flushSpeech(), VOICE_PAUSE_MS);
    };
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        this.voiceError.set('Microphone access was blocked. Allow it in the address bar, or use Type.');
        this.stopListening();
      }
    };
    // Browsers stop recognition after a while of silence; keep going while the mic is on
    rec.onend = () => {
      if (this.listening() && this.recognition === rec) {
        try {
          rec.start();
        } catch {
          this.listening.set(false);
        }
      }
    };
    this.recognition = rec;
    try {
      rec.start();
      this.listening.set(true);
    } catch {
      this.listening.set(false);
    }
  }

  private flushSpeech(): void {
    const text = this.spoken.trim();
    if (!text || this.thinking()) {
      if (text) this.voiceTimer = setTimeout(() => this.flushSpeech(), 600);
      return;
    }
    this.spoken = '';
    this.liveDraft.set('');
    this.teach(text, 'voice');
  }

  private stopListening(): void {
    this.listening.set(false);
    clearTimeout(this.voiceTimer);
    const rec = this.recognition;
    this.recognition = undefined;
    rec?.stop();
    if (this.spoken.trim()) this.flushSpeech();
    this.liveDraft.set('');
  }

  // ------------------------------------------------------------------ helpers
  protected flagText(text: string): string {
    return text.replace('{name}', this.persona().name);
  }

  protected link(url: string | null | undefined): string | null {
    return this.api.absoluteUrl(url);
  }

  protected value(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  ngOnDestroy(): void {
    clearInterval(this.countdown);
    this.timers.forEach(clearTimeout);
    this.stopListening();
  }
}
