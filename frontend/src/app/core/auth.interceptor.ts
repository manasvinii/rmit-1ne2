import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { API_BASE } from './api.service';
import { AuthService } from './auth.service';

/** Adds the bearer token to backend calls; an expired session sends the student back to /login. */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith(API_BASE)) return next(req);
  const auth = inject(AuthService);
  const router = inject(Router);
  const token = auth.token();
  const authed = token ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;
  return next(authed).pipe(
    catchError((e: unknown) => {
      const isLogin = /\/(login|signup|api\/demo-login)$/.test(req.url);
      // A 401 from /canvas/* means the stored Canvas token expired, not the Pupil session
      const isCanvas = req.url.startsWith(`${API_BASE}/canvas/`);
      if (e instanceof HttpErrorResponse && e.status === 401 && !isLogin && !isCanvas) {
        auth.logout();
        router.navigate(['/login'], { replaceUrl: true, state: { from: router.url } });
      }
      return throwError(() => e);
    }),
  );
};
