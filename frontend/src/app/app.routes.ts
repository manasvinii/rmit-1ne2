import { Routes } from '@angular/router';
import { authGuard } from './core/auth.guard';
import { AppLayout } from './shared/app-layout/app-layout';
import { Ask } from './pages/ask/ask';
import { Home } from './pages/home/home';
import { Login } from './pages/login/login';
import { Session } from './pages/session/session';
import { Setup } from './pages/setup/setup';
import { UnderstandingMap } from './pages/understanding-map/understanding-map';

export const routes: Routes = [
  { path: 'login', component: Login, title: 'Sign in · Pupil' },

  // Pages that share the dark sidebar
  {
    path: '',
    component: AppLayout,
    canActivate: [authGuard],
    children: [
      { path: '', component: Home, title: 'Pupil · learn by teaching' },
      { path: 'setup', component: Setup, title: 'New teaching session · Pupil' },
      { path: 'map', component: UnderstandingMap, title: 'Understanding map · Pupil' },
      { path: 'ask', component: Ask, title: 'Ask Pupil · Pupil' },
    ],
  },

  // The teaching session is full-screen, without the sidebar
  { path: 'session', component: Session, canActivate: [authGuard], title: 'Teaching · Pupil' },

  { path: '**', redirectTo: '' },
];
