import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { BarCard } from './BarCard';
import { ChartCard } from './ChartCard';
import { PAGE_SIZE, padCount, pageWindow } from './Pager';
import { LineChart, describeSeries, markerPath, tickStep, type LineSeries } from './LineChart';

afterEach(cleanup);

const points = [
  { day: '2026-10-01', value: 2 },
  { day: '2026-10-02', value: 4 },
  { day: '2026-10-03', value: null },
  { day: '2026-10-04', value: 8 },
];
const series: LineSeries[] = [
  { id: 'a', label: 'Products edited', points, marker: 'circle', color: 'var(--primary)' },
  { id: 'b', label: 'New products', points: points.map((p) => ({ ...p, value: p.value === null ? null : p.value / 2 })), marker: 'triangle', dash: '6 4', color: 'var(--secondary)' },
];
const format = (value: number) => String(value);

describe('LineChart', () => {
  it('draws one line per series, with a gap where a value is not known', () => {
    const { container } = render(<LineChart series={series} format={format} label="Edits" />);
    const lines = container.querySelectorAll('.chart__line');
    expect(lines).toHaveLength(2);
    expect(lines[0].getAttribute('d')).toMatch(/M[^M]*M/); // two pieces: the missing day breaks the line
    expect(lines[1].getAttribute('stroke-dasharray')).toBe('6 4');
  });

  it('marks every known point with the series own marker', () => {
    const { container } = render(<LineChart series={series} format={format} label="Edits" />);
    expect(container.querySelectorAll('.chart__marker')).toHaveLength(6);
    expect(markerPath('circle', 44)).not.toBe(markerPath('triangle', 44));
    expect(markerPath('diamond', 44)).not.toBe(markerPath('square', 44));
  });

  it('is named and described for a screen reader, with the first and last value of each series', () => {
    render(<LineChart series={series} format={format} label="Edits" />);
    const group = screen.getByRole('group');
    expect(group.getAttribute('aria-label')).toContain('Edits.');
    expect(group.getAttribute('aria-label')).toContain('Products edited: 2 on 1 Oct 2026, 8 on 4 Oct 2026');
    expect(group.getAttribute('aria-label')).toContain('New products: 1 on 1 Oct 2026, 4 on 4 Oct 2026');
    expect(group.getAttribute('tabindex')).toBe('0');
  });

  it('reads values day by day with the arrow keys, says when a value is not known, and clears on Escape', () => {
    render(<LineChart series={series} format={format} label="Edits" />);
    const group = screen.getByRole('group');
    fireEvent.keyDown(group, { key: 'ArrowRight' });
    expect(group.querySelector('.chart__readout')?.textContent).toBe('1 Oct 2026: Products edited 2, New products 1');
    fireEvent.keyDown(group, { key: 'ArrowRight' });
    fireEvent.keyDown(group, { key: 'ArrowRight' });
    expect(group.querySelector('.chart__readout')?.textContent).toBe('3 Oct 2026: Products edited not known, New products not known');
    fireEvent.keyDown(group, { key: 'End' });
    expect(group.querySelector('.chart__readout')?.textContent).toContain('4 Oct 2026');
    fireEvent.keyDown(group, { key: 'Escape' });
    expect(group.querySelector('.chart__readout')?.textContent).toBe('');
  });

  it('lists the legend with a line style and a marker for each series', () => {
    render(<LineChart series={series} format={format} label="Edits" />);
    const items = screen.getAllByRole('listitem');
    expect(items.map((li) => li.textContent)).toEqual(['Products edited', 'New products']);
    expect(items[1].querySelector('line')?.getAttribute('stroke-dasharray')).toBe('6 4');
  });

  it('describes a series with no values', () => {
    expect(describeSeries([{ ...series[0], points: [{ day: '2026-10-01', value: null }] }], format)).toBe('Products edited: no values');
  });

  it('labels about six days along the axis, whatever the range', () => {
    expect(tickStep(6)).toBe(1);
    expect(tickStep(15)).toBe(3);
    expect(tickStep(28)).toBe(5);
  });
});

describe('ChartCard', () => {
  it('shows the very same numbers as a table, with the unknown value in words', () => {
    render(<ChartCard title="Edits per day" series={series} format={format} unknownText="fewer than 5" />);
    expect(screen.queryByRole('table')).toBeNull();
    const button = screen.getByRole('button', { name: 'Show as a table' });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(button);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    const table = screen.getByRole('table');
    const rows = within(table).getAllByRole('row').map((row) => [...row.children].map((c) => c.textContent));
    expect(rows[0]).toEqual(['Day', 'Products edited', 'New products']);
    // newest day first
    expect(rows[1]).toEqual(['4 Oct 2026', '8', '4']);
    expect(rows[2]).toEqual(['3 Oct 2026', 'fewer than 5', 'fewer than 5']);
    expect(rows[4]).toEqual(['1 Oct 2026', '2', '1']);
    expect(rows).toHaveLength(5);
    fireEvent.click(screen.getByRole('button', { name: 'Hide the table' }));
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('puts the title in a heading of the level it is given', () => {
    render(<ChartCard title="Edits per day" series={series} format={format} unknownText="n/a" headingLevel={2} />);
    expect(screen.getByRole('heading', { level: 2, name: 'Edits per day' })).toBeTruthy();
  });
});

const manyDays = (count: number): LineSeries[] => [
  {
    id: 'm',
    label: 'Value',
    marker: 'circle',
    color: 'var(--primary)',
    points: Array.from({ length: count }, (_, i) => ({ day: new Date(Date.UTC(2026, 8, 30 + i)).toISOString().slice(0, 10), value: i })),
  },
];

describe('paging of the table behind a chart', () => {
  it('computes which rows a page shows, and pulls a page number back into range', () => {
    expect(PAGE_SIZE).toBe(10);
    expect(pageWindow(28, 0)).toEqual({ start: 0, end: 10, pages: 3 });
    expect(pageWindow(28, 2)).toEqual({ start: 20, end: 28, pages: 3 });
    expect(pageWindow(28, 9)).toEqual({ start: 20, end: 28, pages: 3 });
    expect(pageWindow(0, 0)).toEqual({ start: 0, end: 0, pages: 1 });
    expect(pageWindow(10, 0).pages).toBe(1);
    expect(pageWindow(11, 0).pages).toBe(2);
  });

  it('pads the last page to a full page so the buttons stay put, and pads nothing when there is one page', () => {
    expect(padCount(28, 8)).toBe(2);
    expect(padCount(28, 10)).toBe(0);
    expect(padCount(8, 8)).toBe(0);
    expect(padCount(22, 11, 11)).toBe(0);
  });

  it('shows ten days at a time, newest first, and moves with Previous and Next', () => {
    render(<ChartCard title="Long" series={manyDays(28)} format={format} unknownText="n/a" />);
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    const bodyRows = () => within(screen.getByRole('table')).getAllByRole('row').slice(1).map((row) => row.children[0].textContent);
    expect(bodyRows()).toHaveLength(10);
    expect(bodyRows()[0]).toBe('27 Oct 2026');
    expect(screen.getByRole('status').textContent).toBe('Days 1 to 10 of 28');
    expect((screen.getByRole('button', { name: 'Previous' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(bodyRows()[0]).toBe('17 Oct 2026');
    expect(screen.getByRole('status').textContent).toBe('Days 11 to 20 of 28');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(bodyRows()).toHaveLength(8);
    expect(bodyRows()[7]).toBe('30 Sep 2026');
    expect(screen.getByRole('status').textContent).toBe('Days 21 to 28 of 28');
    expect((screen.getByRole('button', { name: 'Next' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('starts again on the first page each time the table is opened', () => {
    render(<ChartCard title="Long" series={manyDays(28)} format={format} unknownText="n/a" />);
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    fireEvent.click(screen.getByRole('button', { name: 'Hide the table' }));
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    expect(screen.getByRole('status').textContent).toBe('Days 1 to 10 of 28');
  });

  it('draws no pager when ten days or fewer fit on one page', () => {
    render(<ChartCard title="Short" series={manyDays(10)} format={format} unknownText="n/a" />);
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    expect(screen.queryByRole('button', { name: 'Next' })).toBeNull();
  });

  it('opens and closes each card on its own', () => {
    render(
      <>
        <ChartCard title="First" series={manyDays(12)} format={format} unknownText="n/a" />
        <ChartCard title="Second" series={manyDays(12)} format={format} unknownText="n/a" />
      </>,
    );
    const [firstButton, secondButton] = screen.getAllByRole('button', { name: 'Show as a table' });
    fireEvent.click(secondButton);
    expect(screen.getAllByRole('table')).toHaveLength(1);
    expect(firstButton.getAttribute('aria-expanded')).toBe('false');
    expect(secondButton.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(firstButton);
    expect(screen.getAllByRole('table')).toHaveLength(2);
    fireEvent.click(secondButton);
    expect(screen.getAllByRole('table')).toHaveLength(1);
    expect(firstButton.getAttribute('aria-expanded')).toBe('true');
  });
});

describe('a window onto a long history', () => {
  // 150 days from Thu 1 Oct 2026.
  const long = (value: (i: number) => number): LineSeries[] => [
    {
      id: 'a',
      label: 'Products edited',
      points: Array.from({ length: 150 }, (_, i) => ({ day: new Date(Date.UTC(2026, 9, 1 + i)).toISOString().slice(0, 10), value: value(i) })),
      marker: 'circle',
      color: 'var(--primary)',
      rollup: 'sum',
    },
  ];
  const spike = (i: number) => (i < 10 ? 1000 : 5);

  it('fits the y-axis to what is in view, so an old spike does not flatten the recent days', () => {
    const { container, rerender } = render(<LineChart series={long(spike)} format={format} label="Edits" size={30} start={0} />);
    const ticks = () => [...container.querySelectorAll('.chart__tick')].map((t) => t.textContent);
    expect(ticks()).toContain('1000');
    rerender(<LineChart series={long(spike)} format={format} label="Edits" size={30} start={100} />);
    expect(ticks()).not.toContain('1000');
  });

  it('says which days are in view', () => {
    render(<LineChart series={long(() => 1)} format={format} label="Edits" size={30} start={0} onStart={() => undefined} />);
    expect(screen.getByRole('group').getAttribute('aria-label')).toContain('Showing 1 Oct 2026 to 30 Oct 2026.');
  });

  it('pans with shift and the arrow keys', () => {
    const seen: number[] = [];
    render(<LineChart series={long(() => 1)} format={format} label="Edits" size={40} start={20} onStart={(s) => seen.push(s)} />);
    const group = screen.getByRole('group');
    fireEvent.keyDown(group, { key: 'ArrowRight', shiftKey: true });
    fireEvent.keyDown(group, { key: 'ArrowLeft', shiftKey: true });
    expect(seen).toEqual([30, 10]);
  });

  it('offers days, weeks and months for a series that says how it rolls up, and starts on the newest 60 days', () => {
    render(<ChartCard title="Edits" series={long(() => 1)} format={format} unknownText="not known" />);
    const group = screen.getByRole('radiogroup', { name: 'How much time each point covers' });
    expect(within(group).getAllByRole('radio').map((r) => r.textContent)).toEqual(['Days', 'Weeks', 'Months']);
    expect(screen.getByText(/Showing 30 Dec 2026 to 27 Feb 2027/)).toBeTruthy();
  });

  it('moves the window with the Earlier and Later buttons', () => {
    render(<ChartCard title="Edits" series={long(() => 1)} format={format} unknownText="not known" />);
    expect((screen.getByRole('button', { name: 'Later' }) as HTMLButtonElement).disabled).toBe(true); // already at the newest
    fireEvent.click(screen.getByRole('button', { name: 'Earlier' }));
    expect(screen.getByText(/Showing 30 Nov 2026 to 28 Jan 2027/)).toBeTruthy(); // 30 days earlier
    expect((screen.getByRole('button', { name: 'Later' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('switches the table to weeks, with the right heading, and marks a part of a week', () => {
    render(<ChartCard title="Edits" series={long(() => 1)} format={format} unknownText="not known" />);
    fireEvent.click(screen.getByRole('radio', { name: 'Weeks' }));
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    expect(screen.getByRole('columnheader', { name: 'Week ending' })).toBeTruthy();
    expect(screen.getAllByText(/\(part\)/).length).toBeGreaterThan(0);
  });

  it('offers no weeks or months for a series that does not say how it rolls up', () => {
    const without = long(() => 1).map((s) => ({ ...s, rollup: undefined }));
    render(<ChartCard title="Edits" series={without} format={format} unknownText="not known" />);
    expect(screen.queryByRole('radiogroup', { name: 'How much time each point covers' })).toBeNull();
  });

  it('shows everything at once on request', () => {
    render(<ChartCard title="Edits" series={long(() => 1)} format={format} unknownText="not known" />);
    fireEvent.click(screen.getByRole('button', { name: 'Show all 150 days' }));
    expect(screen.queryByText(/^Showing /)).toBeNull();
    expect(screen.getByRole('button', { name: 'Show the latest 60 days' })).toBeTruthy();
  });
});

describe('the tip that says what a mark stands for', () => {
  it('names the day and every series value at the cursor of a line chart', () => {
    const { container } = render(<LineChart series={series} format={format} label="Edits" />);
    expect(container.querySelector('.chart-tip')).toBeNull();
    fireEvent.keyDown(screen.getByRole('group'), { key: 'ArrowRight' });
    const tip = container.querySelector('.chart-tip');
    expect(tip?.textContent).toContain('1 Oct 2026');
    expect(tip?.textContent).toContain('Products edited');
    expect(tip?.textContent).toContain('New products');
  });

  it('names the row and what its value counts when a bar is pointed at', () => {
    const rows = [{ id: 'a', label: 'Nutrition', value: 12, display: '12%', small: 'en:nutrition' }];
    const { container } = render(<BarCard title="Empty fields" rows={rows} valueHeading="Share left empty" unknownText="fewer than 5" />);
    expect(container.querySelector('.chart-tip')).toBeNull();
    fireEvent.pointerMove(container.querySelector('.bar-chart li') as Element);
    const tip = container.querySelector('.chart-tip');
    expect(tip?.textContent).toContain('Nutrition');
    expect(tip?.textContent).toContain('Share left empty');
    expect(tip?.textContent).toContain('12%');
    expect(tip?.textContent).toContain('en:nutrition');
    fireEvent.pointerLeave(container.querySelector('.bar-chart li') as Element);
    expect(container.querySelector('.chart-tip')).toBeNull();
  });
});
