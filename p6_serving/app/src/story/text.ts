import { clamp01, lerp } from './timeline';

const GLYPHS = 'abcdefghijklmnopqrstuvwxyz0123456789_-';

/** A glyph that depends only on its place and the step, so the same progress always shows the same scramble (and scrolling back replays it). */
function glyph(place: number, step: number): string {
  const mixed = Math.imul(place + 1, 2654435761) ^ Math.imul(step + 7, 40503);
  return GLYPHS[Math.abs(mixed) % GLYPHS.length];
}

/**
 * One text turning into another as `t` goes from 0 to 1: the letters of the new text settle from left to right while the rest churn, and the
 * length slides from the old length to the new. At 0 it is exactly `from`, at 1 exactly `to`.
 */
export function scrambleMix(from: string, to: string, t: number): string {
  if (t <= 0) return from;
  if (t >= 1) return to;
  const length = Math.round(lerp(from.length, to.length, t));
  const settled = Math.floor(t * to.length);
  const step = Math.floor(t * 30);
  let out = '';
  for (let i = 0; i < length; i++) {
    if (i < settled) out += to[i] ?? '';
    else out += (to[i] ?? from[i]) === ' ' ? ' ' : glyph(i, step);
  }
  return out;
}

/** A whole number on its way from `a` to `b`. */
export function countAt(a: number, b: number, t: number): number {
  return Math.round(lerp(a, b, clamp01(t)));
}
