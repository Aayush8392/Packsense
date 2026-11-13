import { describe, expect, it } from 'vitest';
import { clampStart, fitDomain, windowSize } from './window';

describe('windowSize', () => {
  it('shows a couple of months of days, half a year of weeks and two years of months, and half as many on a small chart', () => {
    expect([windowSize('day', false), windowSize('week', false), windowSize('month', false)]).toEqual([60, 26, 24]);
    expect([windowSize('day', true), windowSize('week', true), windowSize('month', true)]).toEqual([30, 13, 12]);
  });
});

describe('clampStart', () => {
  it('keeps a window inside the series', () => {
    expect(clampStart(-5, 100, 30)).toBe(0);
    expect(clampStart(90, 100, 30)).toBe(70);
    expect(clampStart(10, 100, 30)).toBe(10);
    expect(clampStart(4, 20, 30)).toBe(0);
  });
});

describe('fitDomain', () => {
  it('starts a count at zero and ends at its largest value in view', () => {
    expect(fitDomain([3, 8, null, 5], true)).toEqual([0, 8]);
  });

  it('gives an empty or all-zero view a usable span', () => {
    expect(fitDomain([], true)).toEqual([0, 1]);
    expect(fitDomain([null, null], false)).toEqual([0, 1]);
    expect(fitDomain([0, 0], false)).toEqual([0, 1]);
  });

  it('lets a rate start higher when its values vary by a tenth of their level or more', () => {
    const [low, high] = fitDomain([8.4, 9.4, 9], false);
    expect(low).toBeGreaterThan(7.5);
    expect(low).toBeLessThan(8.4);
    expect(high).toBeGreaterThan(9.4);
  });

  it('keeps zero for a rate that hardly moves, so noise is not drawn as a trend', () => {
    expect(fitDomain([9.08, 9.1, 9.09], false)).toEqual([0, 9.1]);
  });

  it('keeps zero for a rate whose lowest value is under half its highest, so no movement looks bigger than it is', () => {
    expect(fitDomain([2, 9.4], false)).toEqual([0, 9.4]);
  });
});
