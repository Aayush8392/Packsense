import { addDays } from '../format';

/** The opacity of each step of the heatmap, from the lightest (the fewest) to the darkest (the most). */
export const HEAT_OPACITY = [0.14, 0.3, 0.5, 0.75, 1];

export function weekday(iso: string): number {
  return (new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7; // Monday is 0
}

/** The Monday of the week that holds `iso`. */
export function mondayOf(iso: string): string {
  return addDays(iso, -weekday(iso));
}

/**
 * The cut points between the steps of the heatmap: the values at a fifth, two fifths, three fifths and four fifths of the sorted days, so each
 * step holds about the same number of days and one huge day cannot turn every other day pale. Cut points that fall on the same value are merged,
 * so a series with few different values gets fewer steps.
 */
export function heatCuts(values: number[]): number[] {
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length === 0) return [];
  const cuts: number[] = [];
  for (let k = 1; k < HEAT_OPACITY.length; k++) {
    const value = sorted[Math.floor((k * sorted.length) / HEAT_OPACITY.length)];
    if (value > sorted[0] && (cuts.length === 0 || value > cuts[cuts.length - 1])) cuts.push(value);
  }
  return cuts;
}

/** Which step a value falls in: the number of cut points it has reached. */
export function heatLevel(value: number, cuts: number[]): number {
  return cuts.filter((cut) => value >= cut).length;
}

/** The opacity of a step, spread over however many steps there are. */
export function heatOpacity(level: number, levels: number): number {
  if (levels <= 1) return HEAT_OPACITY[HEAT_OPACITY.length - 1];
  return HEAT_OPACITY[Math.round((level / (levels - 1)) * (HEAT_OPACITY.length - 1))];
}

export interface HeatGrid {
  /** The Monday of each column. */
  weeks: string[];
  /** Where a day sits: its column and its row (Monday is row 0). */
  place: (iso: string) => { col: number; row: number };
}

/** The columns (weeks, Monday first) that hold the days from `first` to `last`. */
export function heatGrid(first: string, last: string): HeatGrid {
  const start = mondayOf(first);
  const weeks: string[] = [];
  for (let monday = start; monday <= last; monday = addDays(monday, 7)) weeks.push(monday);
  return {
    weeks,
    place: (iso) => ({ col: weeks.indexOf(mondayOf(iso)), row: weekday(iso) }),
  };
}
