/*
 * PUPIL BACKEND API
 * -----------------
 * Talks to the FastAPI server in backend/ (uvicorn app.main:app --port 8000).
 * Every request carries the backend-issued bearer token (see auth.interceptor.ts).
 * To use another address, change API_BASE below.
 */
import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, shareReplay, throwError } from 'rxjs';
import {
  Assignment,
  ChatAnswer,
  Gap,
  Material,
  PersonaId,
  SessionSummary,
  SubjectsResponse,
  TeachingSession,
  UnderstandingMapData,
} from './models';

export const API_BASE = 'http://localhost:8000';

/** Which weeks a request is about: one week, weeks 1..N, or any combination. */
export interface WeekScope {
  week: number;
  mode: 'single' | 'range' | 'pick';
  weeks?: number[];
}

export interface StartSessionRequest extends WeekScope {
  subjectId: string;
  persona: PersonaId;
  input: 'voice' | 'text';
  length: number;
  exclude: string[];
  include: string[];
}

function scopeParams(s: WeekScope, params = new HttpParams()): HttpParams {
  if (s.mode === 'pick' && s.weeks?.length) return params.set('weeks', s.weeks.join(','));
  return params.set('week', s.week).set('mode', s.mode === 'range' ? 'range' : 'single');
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  // Subjects rarely change during a visit, so the whole app shares one request.
  private subjects$?: Observable<SubjectsResponse>;
  private materialsCache = new Map<string, Observable<Material[]>>();

  /** { currentWeek, totalWeeks, subjects: [{ id, code, name, topics, currentWeek, ... }] } */
  getSubjects(refresh = false): Observable<SubjectsResponse> {
    if (!this.subjects$ || refresh) {
      this.subjects$ = this.http.get<SubjectsResponse>(`${API_BASE}/api/subjects`).pipe(
        catchError((e) => {
          this.subjects$ = undefined; // let the next call try again
          return throwError(() => friendlyError(e));
        }),
        shareReplay(1),
      );
    }
    return this.subjects$;
  }

  /** Pull the latest courses and assignments from Canvas (server-side, with the student's stored token). */
  syncCanvas(): Observable<unknown> {
    return this.http.post(`${API_BASE}/canvas/sync`, {}).pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  /** Materials for the chosen week(s): [{ id, kind, title, sub, off, source, items? }] */
  getMaterials(subjectId: string, scope: WeekScope): Observable<Material[]> {
    const params = scopeParams(scope);
    const key = `${subjectId}|${params.toString()}`;
    let req = this.materialsCache.get(key);
    if (!req) {
      req = this.http.get<Material[]>(`${API_BASE}/api/subjects/${subjectId}/materials`, { params }).pipe(
        catchError((e) => {
          this.materialsCache.delete(key);
          return throwError(() => friendlyError(e));
        }),
        shareReplay(1),
      );
      this.materialsCache.set(key, req);
    }
    return req;
  }

  /** Plain text of the chosen materials: exactly what the AI student is allowed to know. */
  getContent(subjectId: string, scope: WeekScope, opts: { exclude?: string[]; include?: string[] } = {}) {
    const params = scopeParams(scope)
      .set('exclude', (opts.exclude || []).join(','))
      .set('include', (opts.include || []).join(','));
    return this.http
      .get<{ topic: string; text: string; materials: unknown[] }>(`${API_BASE}/api/subjects/${subjectId}/content`, { params })
      .pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  /** Links in material rows are short-lived signed URLs, so they open in a new tab without the token. */
  materialLink(m: Material): string | null {
    return this.absoluteUrl(m.source?.url);
  }

  absoluteUrl(url: string | null | undefined): string | null {
    if (!url) return null;
    return url.startsWith('/') ? API_BASE + url : url;
  }

  /** Zip of the selected materials. Needs the token, so it is fetched and saved rather than linked. */
  downloadZip(subjectId: string, scope: WeekScope, opts: { exclude?: string[]; include?: string[] } = {}): void {
    const params = scopeParams(scope)
      .set('exclude', (opts.exclude || []).join(','))
      .set('include', (opts.include || []).join(','));
    this.http
      .get(`${API_BASE}/api/subjects/${subjectId}/download`, { params, responseType: 'blob', observe: 'response' })
      .subscribe((res) => {
        const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '')?.[1] || 'materials.zip';
        const a = document.createElement('a');
        a.href = URL.createObjectURL(res.body!);
        a.download = name;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      });
  }

  // ---------------------------------------------------------------- teaching sessions
  startSession(body: StartSessionRequest): Observable<TeachingSession> {
    const payload = {
      subjectId: body.subjectId,
      persona: body.persona,
      input: body.input,
      length: body.length,
      exclude: body.exclude,
      include: body.include,
      ...(body.mode === 'pick' && body.weeks?.length
        ? { weeks: body.weeks }
        : { week: body.week, mode: body.mode === 'range' ? 'range' : 'single' }),
    };
    return this.http.post<TeachingSession>(`${API_BASE}/api/sessions`, payload).pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  getSession(id: string): Observable<TeachingSession> {
    return this.http.get<TeachingSession>(`${API_BASE}/api/sessions/${id}`).pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  sendMessage(id: string, text: string, via: 'voice' | 'text'): Observable<TeachingSession> {
    return this.http
      .post<TeachingSession>(`${API_BASE}/api/sessions/${id}/messages`, { text, via })
      .pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  hint(id: string): Observable<TeachingSession> {
    return this.http.post<TeachingSession>(`${API_BASE}/api/sessions/${id}/hint`, {}).pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  endSession(id: string): Observable<UnderstandingMapData> {
    return this.http
      .post<UnderstandingMapData>(`${API_BASE}/api/sessions/${id}/end`, {})
      .pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  /** New session on the same weeks and material: weak spots only, or everything with another student. */
  reteach(id: string, persona?: PersonaId): Observable<TeachingSession> {
    return this.http
      .post<TeachingSession>(`${API_BASE}/api/sessions/${id}/reteach`, persona ? { persona } : {})
      .pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  getMap(id: string): Observable<UnderstandingMapData> {
    return this.http.get<UnderstandingMapData>(`${API_BASE}/api/sessions/${id}/map`).pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  listSessions(): Observable<SessionSummary[]> {
    return this.http.get<SessionSummary[]>(`${API_BASE}/api/sessions`).pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  getGaps(): Observable<Gap[]> {
    return this.http.get<Gap[]>(`${API_BASE}/api/gaps`).pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  /** Ask Pupil: the backend routes to Canvas data, lecture search or the knowledge graph and cites sources. */
  ask(query: string, courseId?: string | null): Observable<ChatAnswer> {
    return this.http
      .post<ChatAnswer>(`${API_BASE}/query`, courseId ? { query, course_id: courseId } : { query })
      .pipe(catchError((e) => throwError(() => friendlyError(e))));
  }

  getAssignments(): Observable<Assignment[]> {
    return this.http.get<Assignment[]>(`${API_BASE}/me/assignments`).pipe(catchError((e) => throwError(() => friendlyError(e))));
  }
}

export function friendlyError(e: unknown): Error {
  if (e instanceof HttpErrorResponse) {
    if (e.status === 0) return new Error(`Can't reach the Pupil backend at ${API_BASE}. Is it running?`);
    const detail = e.error && (e.error as { detail?: unknown }).detail;
    if (typeof detail === 'string') return new Error(detail);
    return new Error(`${e.status} ${e.statusText}`);
  }
  return e instanceof Error ? e : new Error(String(e));
}
