import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { PersonaId } from '../../core/models';

/**
 * The three AI students (Pip, Sage, Milo), drawn as inline SVG. The <svg> is the component:
 *   <svg appAvatar persona="pip" [size]="120" mood="puzzled" [onDark]="true"></svg>
 */
@Component({
  selector: 'svg[appAvatar]',
  templateUrl: './avatar.html',
  styleUrl: './avatar.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    viewBox: '0 0 120 120',
    '[attr.width]': 'size()',
    '[attr.height]': 'size()',
    '[attr.role]': 'label() ? "img" : null',
    '[attr.aria-label]': 'label() || null',
    '[attr.aria-hidden]': 'label() ? null : "true"',
  },
})
export class Avatar {
  readonly persona = input<PersonaId>('pip');
  readonly size = input(64);
  readonly mood = input<'curious' | 'puzzled'>('curious');
  readonly onDark = input(false);
  readonly label = input<string | undefined>(undefined);
}
