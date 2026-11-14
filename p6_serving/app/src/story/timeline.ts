/** Small pieces of arithmetic the scroll story is built from. Everything here is a pure function of the scroll progress, a number from 0 to 1. */

export const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/** Slow at both ends, quick in the middle: the way a camera eases in and out of a move. */
export const ease = (t: number): number => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

/** How far `p` is through the stretch from `a` to `b`, as 0 to 1 (0 before it, 1 after it). */
export const seg = (p: number, a: number, b: number): number => clamp01((p - a) / (b - a));

export interface Beat {
  id: 'file' | 'raw' | 'clean' | 'tables' | 'page';
  /** The scroll progress the beat starts and ends at. */
  from: number;
  to: number;
}

/** The five stages of the story, one after the other, covering the whole scroll. */
export const BEATS: Beat[] = [
  { id: 'file', from: 0, to: 0.2 },
  { id: 'raw', from: 0.2, to: 0.42 },
  { id: 'clean', from: 0.42, to: 0.64 },
  { id: 'tables', from: 0.64, to: 0.84 },
  { id: 'page', from: 0.84, to: 1 },
];

/** The index of the stage that holds progress `p`. */
export function beatAt(p: number): number {
  const index = BEATS.findIndex((beat) => p < beat.to);
  return index === -1 ? BEATS.length - 1 : index;
}

/** How visible a caption is: fully inside its stage, fading over `edge` at each end. */
export function captionOpacity(p: number, beat: Beat, edge = 0.03): number {
  return Math.min(seg(p, beat.from - edge, beat.from), 1 - seg(p, beat.to, beat.to + edge));
}
