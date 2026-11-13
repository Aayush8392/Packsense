import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { WaterfallCard, axisFloor, runningTotals, type WaterfallStep } from './WaterfallCard';

afterEach(cleanup);

const steps: WaterfallStep[] = [
  { id: 's', label: 'Open flags', sub: '1 Oct 2026', value: 209478, total: true, meaning: 'Where it began.' },
  { id: 'c', label: 'Came with new products', value: 20003, total: false, meaning: 'Arrived already flagged.' },
  { id: 'o', label: 'Opened on held products', value: 8587, total: false, meaning: 'Appeared on a held product.' },
  { id: 'v', label: 'Ended', value: -9007, total: false, meaning: 'Fixed, or the product left.' },
  { id: 'r', label: 'Not itemised', value: 266, total: false, meaning: 'Hidden counts.' },
  { id: 'e', label: 'Open flags', sub: '31 Oct 2026', value: 229327, total: true, meaning: 'Where it ended.' },
];
const format = (v: number) => v.toLocaleString('en-GB');
const short = (v: number) => (Math.abs(v) >= 1000 ? `${Math.round(v / 1000)}k` : String(v));

describe('runningTotals', () => {
  it('moves the total with each change and restarts it at a total', () => {
    expect(runningTotals(steps)).toEqual([209478, 229481, 238068, 229061, 229327, 229327]);
  });
});

describe('axisFloor', () => {
  it('starts at zero when a total falls to half the highest or lower, so no step is made to look bigger than it is', () => {
    expect(axisFloor(318882, 1919323)).toBe(0);
  });

  it('starts a little below the lowest total when they all stay high, on a round number', () => {
    const floor = axisFloor(209478, 238068);
    expect(floor).toBeGreaterThan(100000);
    expect(floor).toBeLessThan(209478);
    expect(floor % 10000).toBe(0);
  });
});

describe('WaterfallCard', () => {
  const props = { title: 'Open flags', steps, format, short, valueHeading: 'Open flags' };

  it('draws a bar for every step, the totals apart from the rises and the falls', () => {
    const { container } = render(<WaterfallCard {...props} />);
    expect(container.querySelectorAll('.waterfall__bar')).toHaveLength(6);
    expect(container.querySelectorAll('.waterfall__bar--total')).toHaveLength(2);
    expect(container.querySelectorAll('.waterfall__bar--up')).toHaveLength(3);
    expect(container.querySelectorAll('.waterfall__bar--down')).toHaveLength(1);
  });

  it('says that the scale does not start at zero when it does not', () => {
    render(<WaterfallCard {...props} />);
    expect(screen.getByText(/The scale starts at .*, not at zero/)).toBeTruthy();
  });

  it('says nothing about a cut scale when it starts at zero', () => {
    const wide = steps.map((s) => (s.id === 'c' ? { ...s, value: 1_600_000 } : s));
    render(<WaterfallCard {...props} steps={wide.map((s) => (s.id === 's' ? { ...s, value: 300_000 } : s))} />);
    expect(screen.queryByText(/not at zero/)).toBeNull();
  });

  it('names the step, its change, the running total and what it means, with the arrow keys', () => {
    const { container } = render(<WaterfallCard {...props} />);
    const group = screen.getByRole('group');
    fireEvent.keyDown(group, { key: 'ArrowRight' });
    fireEvent.keyDown(group, { key: 'ArrowRight' });
    const tip = container.querySelector('.chart-tip');
    expect(tip?.textContent).toContain('Came with new products');
    expect(tip?.textContent).toContain('+20,003');
    expect(tip?.textContent).toContain('229,481');
    expect(tip?.textContent).toContain('Arrived already flagged.');
    expect(group.querySelector('.chart__readout')?.textContent).toContain('running total 229,481');
    fireEvent.keyDown(group, { key: 'Escape' });
    expect(container.querySelector('.chart-tip')).toBeNull();
  });

  it('gives a minus sign to a fall and offers the table', () => {
    render(<WaterfallCard {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    expect(screen.getByRole('cell', { name: '−9,007' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'Running total' })).toBeTruthy();
  });
});
