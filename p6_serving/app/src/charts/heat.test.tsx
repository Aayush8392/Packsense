import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { addDays } from '../format';
import { heatCuts, heatGrid, heatLevel, heatOpacity, mondayOf, weekday } from './heat';
import { HeatmapCard } from './HeatmapCard';

afterEach(cleanup);

describe('the calendar grid', () => {
  it('starts a week on Monday', () => {
    expect(weekday('2026-10-05')).toBe(0); // a Monday
    expect(weekday('2026-10-04')).toBe(6); // a Sunday
    expect(mondayOf('2026-10-01')).toBe('2026-09-28'); // a Thursday
  });

  it('puts every day in its week column and its weekday row', () => {
    const grid = heatGrid('2026-10-01', '2026-10-31');
    expect(grid.weeks).toEqual(['2026-09-28', '2026-10-05', '2026-10-12', '2026-10-19', '2026-10-26']);
    expect(grid.place('2026-10-01')).toEqual({ col: 0, row: 3 });
    expect(grid.place('2026-10-31')).toEqual({ col: 4, row: 5 });
  });
});

describe('the steps of the heatmap', () => {
  it('cuts a series into steps of about the same number of days, so one huge day does not turn the rest pale', () => {
    const values = [10, 11, 12, 13, 14, 15, 16, 17, 18, 5000];
    const cuts = heatCuts(values);
    expect(cuts).toEqual([12, 14, 16, 18]);
    expect(values.map((v) => heatLevel(v, cuts))).toEqual([0, 0, 1, 1, 2, 2, 3, 3, 4, 4]);
  });

  it('merges cut points that fall on the same value, so a series with few values has fewer steps', () => {
    expect(heatCuts([1, 1, 1, 1, 1, 1, 2, 2, 2, 2])).toEqual([2]);
    expect(heatCuts([5, 5, 5])).toEqual([]);
    expect(heatCuts([])).toEqual([]);
  });

  it('spreads the opacity over however many steps there are, lightest to darkest', () => {
    expect(heatOpacity(0, 5)).toBeLessThan(heatOpacity(4, 5));
    expect(heatOpacity(1, 2)).toBe(1);
    expect(heatOpacity(0, 1)).toBe(1);
  });
});

describe('HeatmapCard', () => {
  const points = Array.from({ length: 31 }, (_, i) => ({ day: addDays('2026-10-01', i), value: i === 4 ? null : (i + 1) * 10 }));
  const format = (v: number) => String(v);

  it('draws a square for every day, a dashed one where the count is hidden, and nothing before the first day', () => {
    const { container } = render(<HeatmapCard title="Edits" points={points} label="Products edited" format={format} unknownText="fewer than 5" />);
    expect(container.querySelectorAll('.heatmap__cell')).toHaveLength(31);
    expect(container.querySelectorAll('.heatmap__cell rect[stroke-dasharray]')).toHaveLength(1);
  });

  it('names the weekday, the date and the value at the cursor, and moves by day and by week with the arrow keys', () => {
    const { container } = render(<HeatmapCard title="Edits" points={points} label="Products edited" format={format} unknownText="fewer than 5" />);
    const group = screen.getByRole('group');
    fireEvent.keyDown(group, { key: 'End' });
    expect(group.querySelector('.chart__readout')?.textContent).toBe('Saturday 31 Oct 2026: Products edited 310');
    fireEvent.keyDown(group, { key: 'ArrowLeft' });
    expect(group.querySelector('.chart__readout')?.textContent).toBe('Saturday 24 Oct 2026: Products edited 240');
    fireEvent.keyDown(group, { key: 'ArrowUp' });
    expect(group.querySelector('.chart__readout')?.textContent).toBe('Friday 23 Oct 2026: Products edited 230');
    expect(container.querySelector('.chart-tip')?.textContent).toContain('Friday 23 Oct 2026');
    fireEvent.keyDown(group, { key: 'Home' });
    fireEvent.keyDown(group, { key: 'ArrowRight' });
    expect(group.querySelector('.chart__readout')?.textContent).toContain('Thursday 8 Oct 2026');
    fireEvent.keyDown(group, { key: 'Escape' });
    expect(group.querySelector('.chart__readout')?.textContent).toBe('');
  });

  it('says "fewer than 5" for a hidden day and offers the same numbers as a table', () => {
    render(<HeatmapCard title="Edits" points={points} label="Products edited" format={format} unknownText="fewer than 5" />);
    fireEvent.keyDown(screen.getByRole('group'), { key: 'Home' });
    fireEvent.keyDown(screen.getByRole('group'), { key: 'ArrowUp' }); // already the first day
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    expect(screen.getByRole('columnheader', { name: 'Products edited' })).toBeTruthy();
    expect(screen.getAllByRole('row').length).toBeGreaterThan(5);
  });
});
