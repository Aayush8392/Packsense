import type { Grain } from '../data/rollup';

/** How many points a chart shows at first: the newest ones, so a long history never squeezes them together. Small charts show fewer. */
export function windowSize(grain: Grain, compact: boolean): number {
  const size = { day: 60, week: 26, month: 24 }[grain];
  return compact ? Math.round(size / 2) : size;
}

/** The first point of a window of `size` points that is kept inside a series of `total` points. */
export function clampStart(start: number, total: number, size: number): number {
  return Math.min(Math.max(start, 0), Math.max(total - size, 0));
}

/**
 * The span of the y-axis for the values in view. Counts start at zero. A rate or a share (`zeroBase` false) may start higher so a real change
 * stays visible, but only when its values vary by at least a tenth of their level and the lowest is above half the highest. A rate that hardly
 * moves keeps zero, so noise is not drawn as a trend, and a rate that falls to under half keeps zero, so no fall looks bigger than it is.
 */
export function fitDomain(values: (number | null)[], zeroBase: boolean): [number, number] {
  const known = values.filter((v): v is number => v !== null);
  if (known.length === 0) return [0, 1];
  const high = Math.max(...known);
  const low = Math.min(...known);
  if (zeroBase || high <= 0 || low <= high * 0.5 || high - low < high * 0.1) return [0, high === 0 ? 1 : high];
  const pad = (high - low) * 0.15;
  return [Math.max(low - pad, 0), high + pad];
}
