import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { Icon } from '../icon/icon';

const COLORS: Record<string, string> = { E: 'var(--teal)', S: 'var(--amber)', G: 'var(--red)' };

/**
 * Status marker that never relies on colour alone:
 *   E → ✓ (teal)   S → ~ (amber)   G → ! (red)   N/todo → dashed empty circle
 * Usage: <span appStatusIcon status="G" [size]="36" [square]="true"></span>
 */
@Component({
  selector: 'span[appStatusIcon]',
  imports: [Icon],
  templateUrl: './status-icon.html',
  styleUrl: './status-icon.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    'aria-hidden': 'true',
    '[class.sicon]': 'colored()',
    '[class.dot-empty]': '!colored()',
    '[style.width.px]': 'size()',
    '[style.height.px]': 'size()',
    '[style.flex]': '"0 0 " + size() + "px"',
    '[style.border-radius]': 'colored() ? (square() ? round(size() / 3) + "px" : "50%") : null',
    '[style.background]': 'colored() ? color() : null',
    '[style.font-size.px]': 'colored() ? round(size() * 0.55) : null',
  },
})
export class StatusIcon {
  readonly status = input.required<string>();
  readonly size = input(26);
  readonly square = input(false);

  readonly colored = computed(() => this.status() in COLORS);
  readonly color = computed(() => COLORS[this.status()]);
  readonly round = Math.round;
}
