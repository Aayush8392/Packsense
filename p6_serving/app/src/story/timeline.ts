/** Small pieces of arithmetic the scroll story is built from. */

export const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

export interface Beat {
  id: 'file' | 'raw' | 'clean' | 'tables' | 'page';
  /** Where the stage starts and ends on the timeline, in percent of the whole scroll. */
  from: number;
  to: number;
}

/** The five stages of the story, one after the other, covering the whole scroll (timeline units are percent of the scroll). */
export const BEATS: Beat[] = [
  { id: 'file', from: 0, to: 16 },
  { id: 'raw', from: 16, to: 40 },
  { id: 'clean', from: 40, to: 64 },
  { id: 'tables', from: 64, to: 84 },
  { id: 'page', from: 84, to: 100 },
];

/** The index of the stage that holds `percent` (0 to 100) of the scroll. */
export function beatAt(percent: number): number {
  const index = BEATS.findIndex((beat) => percent < beat.to);
  return index === -1 ? BEATS.length - 1 : index;
}
