import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable } from 'rxjs';
import { AuthService } from '../../core/auth.service';
import { User } from '../../core/models';
import { Avatar } from '../../shared/avatar/avatar';
import { Brand } from '../../shared/brand/brand';
import { Icon } from '../../shared/icon/icon';

/** "Sam.Lee_2" → "Sam Lee 2" */
function nameFromEmail(email: string): string {
  const local = email.split('@')[0].replace(/[._-]+/g, ' ').trim();
  return local
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(' ');
}

@Component({
  selector: 'app-login',
  imports: [Brand, Icon, Avatar],
  templateUrl: './login.html',
  styleUrl: './login.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Login {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly mode = signal<'signin' | 'signup'>('signin');
  protected readonly name = signal('');
  protected readonly email = signal('');
  protected readonly password = signal('');
  protected readonly showPassword = signal(false);
  protected readonly remember = signal(true);
  protected readonly error = signal('');
  protected readonly busy = signal<null | 'email' | 'canvas'>(null);

  /** Where to go after signing in (set by the auth guard). */
  private readonly destination: string = history.state?.from || '/';

  constructor() {
    if (this.auth.user()) this.router.navigate(['/'], { replaceUrl: true });
  }

  protected get isSignup(): boolean {
    return this.mode() === 'signup';
  }

  private finish(req: Observable<User>, how: 'email' | 'canvas'): void {
    this.busy.set(how);
    this.error.set('');
    req.subscribe({
      next: () => this.router.navigateByUrl(this.destination, { replaceUrl: true }),
      error: (e: Error) => {
        this.busy.set(null);
        this.error.set(e.message);
      },
    });
  }

  protected continueWithCanvas(): void {
    this.finish(this.auth.loginWithCanvas(this.remember()), 'canvas');
  }

  protected submit(event: Event): void {
    event.preventDefault();
    const email = this.email().trim();
    if (this.isSignup && !this.name().trim()) return this.error.set('Tell us your name so your students know who you are.');
    if (!/^\S+@\S+\.\S+$/.test(email)) return this.error.set('Enter your university email address.');
    const min = this.isSignup ? 8 : 1;
    if (this.password().length < min) return this.error.set(`Your password needs at least ${min} characters.`);
    const name = this.isSignup ? this.name().trim() || nameFromEmail(email) : '';
    this.finish(
      this.isSignup
        ? this.auth.signup(name, email, this.password(), this.remember())
        : this.auth.loginWithPassword(email, this.password(), this.remember()),
      'email',
    );
  }

  protected switchMode(): void {
    this.mode.set(this.isSignup ? 'signin' : 'signup');
    this.error.set('');
  }

  /** Read the text of an <input> event. */
  protected value(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }
}
