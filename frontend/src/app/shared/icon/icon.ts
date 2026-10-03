import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Simple stroke icon set (24×24). The <svg> itself is the component:
 *   <svg appIcon name="mic" [size]="20"></svg>
 */
@Component({
  selector: 'svg[appIcon]',
  templateUrl: './icon.html',
  styleUrl: './icon.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    'aria-hidden': 'true',
    focusable: 'false',
    '[attr.width]': 'size()',
    '[attr.height]': 'size()',
    '[attr.stroke-width]': 'stroke()',
  },
})
export class Icon {
  readonly name = input.required<string>();
  readonly size = input(20);
  readonly stroke = input(1.8);
}
