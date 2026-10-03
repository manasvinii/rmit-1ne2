import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { Brand } from '../brand/brand';
import { Icon } from '../icon/icon';

/** Dark sidebar + page area, shared by Home, Setup and the Understanding Map. */
@Component({
  selector: 'app-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Brand, Icon],
  templateUrl: './app-layout.html',
  styleUrl: './app-layout.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppLayout {
  protected readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly api = inject(ApiService);

  protected readonly nav = [
    { to: '/', label: 'Home', icon: 'home', exact: true },
    { to: '/setup', label: 'Subjects', icon: 'book', exact: false },
    { to: '/map', label: 'Understanding maps', icon: 'map', exact: false },
    { to: '/ask', label: 'Ask Pupil', icon: 'bulb', exact: false },
    { to: '/session', label: 'Past sessions', icon: 'clock', exact: false },
  ];

  /** Text for the "Canvas connected" card, from the backend. */
  protected readonly syncStatus = signal<{ ok: boolean; text: string }>({ ok: true, text: 'Checking Canvas…' });

  constructor() {
    const syncedAt = new Date();
    this.api.getSubjects().subscribe({
      next: (r) => {
        const n = r.subjects.length;
        const time = syncedAt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
        this.syncStatus.set({
          ok: true,
          text: `Synced ${time} · ${n} subject${n === 1 ? '' : 's'} · Week ${r.currentWeek}`,
        });
      },
      error: () => this.syncStatus.set({ ok: false, text: 'Backend not running' }),
    });
  }

  protected logout(): void {
    this.auth.logout();
    this.router.navigate(['/login'], { replaceUrl: true });
  }
}
