/*
 * AUTHENTICATION
 * --------------
 * Signs in against the Pupil backend, which returns a short-lived bearer token. Only that token
 * is kept in the browser: the student's Canvas token stays encrypted on the server.
 *   - Email + password      -> POST /login (and POST /signup to create an account)
 *   - "Continue with Canvas" -> POST /api/demo-login (demo build only: signs in as the demo student
 *     whose Canvas data was synced; a real build would use Canvas OAuth here)
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, catchError, map, switchMap, throwError } from 'rxjs';
import { API_BASE, friendlyError } from './api.service';
import { AuthSession, User } from './models';

const STORAGE_KEY = 'pupil.session';

interface TokenResponse {
  access_token: string;
  user_id: string;
  name?: string | null;
  expires_in: number;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private session = loadSession();

  /** The signed-in user, or null. Read it in templates as auth.user(). */
  readonly user = signal<User | null>(this.session?.user ?? null);

  token(): string | null {
    if (this.session && this.session.expiresAt <= Date.now()) this.logout();
    return this.session?.token ?? null;
  }

  loginWithPassword(email: string, password: string, remember = true): Observable<User> {
    return this.http.post<TokenResponse>(`${API_BASE}/login`, { email, password }).pipe(
      map((t) => this.store(t, { name: t.name || email, email, via: 'email' }, remember)),
      catchError((e) => throwError(() => friendlyError(e))),
    );
  }

  signup(name: string, email: string, password: string, remember = true): Observable<User> {
    return this.http.post(`${API_BASE}/signup`, { name, email, password }).pipe(
      switchMap(() => this.loginWithPassword(email, password, remember)),
      catchError((e) => throwError(() => friendlyError(e))),
    );
  }

  loginWithCanvas(remember = true): Observable<User> {
    return this.http.post<TokenResponse>(`${API_BASE}/api/demo-login`, {}).pipe(
      switchMap((t) => {
        this.store(t, { name: t.name || 'Student', email: '', via: 'canvas' }, remember);
        return this.http.get<{ name: string; email: string }>(`${API_BASE}/api/me`).pipe(
          map((me) => this.store(t, { name: me.name || t.name || 'Student', email: me.email, via: 'canvas' }, remember)),
        );
      }),
      catchError((e) => throwError(() => friendlyError(e))),
    );
  }

  /** Re-read name/email from the backend (e.g. after a Canvas sync updated the profile). */
  refreshProfile(): void {
    if (!this.session) return;
    this.http.get<{ name: string | null; email: string }>(`${API_BASE}/api/me`).subscribe({
      next: (me) => {
        if (!this.session) return;
        const user: User = { ...this.session.user, name: me.name || this.session.user.name, email: me.email || this.session.user.email };
        const remembered = localStorage.getItem(STORAGE_KEY) !== null;
        this.session = { ...this.session, user };
        this.user.set(user);
        if (remembered) saveSession(this.session);
      },
    });
  }

  logout(): void {
    this.session = null;
    this.user.set(null);
    saveSession(null);
  }

  private store(t: TokenResponse, user: User, remember: boolean): User {
    this.session = { user, token: t.access_token, expiresAt: Date.now() + t.expires_in * 1000 };
    this.user.set(user);
    saveSession(remember ? this.session : null);
    return user;
  }
}

function loadSession(): AuthSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const s = raw ? (JSON.parse(raw) as AuthSession) : null;
    return s && s.token && s.expiresAt > Date.now() ? s : null;
  } catch {
    return null;
  }
}

function saveSession(s: AuthSession | null): void {
  try {
    if (s) localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable (private window etc.): stay logged in for this tab only */
  }
}
