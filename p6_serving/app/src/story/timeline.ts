/** Small pieces of arithmetic the scroll story is built from. */

export const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/** The length of the timeline in units. A position on it is "units of scroll"; the whole scroll is TOTAL units. */
export const TOTAL = 180;

export interface Beat {
  id: 'file' | 'raw' | 'clean' | 'tables' | 'history' | 'checks' | 'page';
  /** Where the stage starts and ends on the timeline, in units. */
  from: number;
  to: number;
}

/** The seven stages of the story, one after the other, covering the whole scroll. */
export const BEATS: Beat[] = [
  { id: 'file', from: 0, to: 16 },
  { id: 'raw', from: 16, to: 40 },
  { id: 'clean', from: 40, to: 64 },
  { id: 'tables', from: 64, to: 92 },
  { id: 'history', from: 92, to: 127 },
  { id: 'checks', from: 127, to: 155 },
  { id: 'page', from: 155, to: TOTAL },
];

/** The index of the stage that holds position `units` on the timeline. */
export function beatAt(units: number): number {
  const index = BEATS.findIndex((beat) => units < beat.to);
  return index === -1 ? BEATS.length - 1 : index;
}
