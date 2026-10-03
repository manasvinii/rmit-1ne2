import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** Pupil logo + name. <app-brand [tagline]="false" /> */
@Component({
  selector: 'app-brand',
  templateUrl: './brand.html',
  styleUrl: './brand.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Brand {
  readonly tagline = input(true);
}
