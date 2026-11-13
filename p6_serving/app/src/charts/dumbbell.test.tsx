import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { DumbbellCard, changeShare } from './DumbbellCard';

afterEach(cleanup);

describe('changeShare', () => {
  it('writes the change as a share of where it began', () => {
    expect(changeShare(100, 111)).toBe('+11%');
    expect(changeShare(100, 96)).toBe('−4%');
    expect(changeShare(100, 100)).toBe('no change');
    expect(changeShare(0, 5)).toBe('up from none');
    expect(changeShare(0, 0)).toBe('no change');
  });
});

describe('DumbbellCard', () => {
  const rows = [
    { id: 'a', label: 'No packaging data', small: 'Warning', from: 3_950_841, to: 4_427_329 },
    { id: 'b', label: 'Hidden kind', from: null, to: 1000 },
  ];
  const format = (v: number) => v.toLocaleString('en-GB');
  const props = { title: 'Kinds of flag', fromLabel: '22 Mar 2026', toLabel: '1 Nov 2026', valueHeading: 'Open flags', rows, format, unknownText: 'fewer than 5' };

  it('draws a hollow dot where a row began and a filled dot where it is now, joined by a line, and only the dot that is known', () => {
    const { container } = render(<DumbbellCard {...props} />);
    expect(container.querySelectorAll('.dumbbell__dot--from')).toHaveLength(1);
    expect(container.querySelectorAll('.dumbbell__dot--to')).toHaveLength(2);
    expect(container.querySelectorAll('.dumbbell__link')).toHaveLength(1);
    const from = parseFloat((container.querySelector('.dumbbell__dot--from') as HTMLElement).style.left);
    const to = parseFloat((container.querySelectorAll('.dumbbell__dot--to')[0] as HTMLElement).style.left);
    expect(to).toBeGreaterThan(from);
  });

  it('says that the scale does not start at zero', () => {
    render(<DumbbellCard {...props} />);
    expect(screen.getByText(/The scale starts at .*, not at zero\./)).toBeTruthy();
  });

  it('names the row, both ends and the change when it is pointed at or tabbed to', () => {
    const { container } = render(<DumbbellCard {...props} />);
    fireEvent.pointerMove(container.querySelector('.dumbbell li') as Element);
    const tip = container.querySelector('.chart-tip');
    expect(tip?.textContent).toContain('No packaging data');
    expect(tip?.textContent).toContain('22 Mar 2026');
    expect(tip?.textContent).toContain('4,427,329');
    expect(tip?.textContent).toContain('+12%');
    expect(tip?.textContent).toContain('Warning');
    fireEvent.pointerLeave(container.querySelector('.dumbbell li') as Element);
    expect(container.querySelector('.chart-tip')).toBeNull();
    fireEvent.focus(container.querySelectorAll('.dumbbell li')[1]);
    expect(container.querySelector('.chart-tip')?.textContent).toContain('fewer than 5');
  });

  it('reads each row to a screen reader and offers the same numbers as a table', () => {
    const { container } = render(<DumbbellCard {...props} />);
    expect(container.querySelector('.dumbbell li')?.getAttribute('aria-label')).toBe('No packaging data: 3,950,841 on 22 Mar 2026, 4,427,329 on 1 Nov 2026, +12%');
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    expect(screen.getByRole('columnheader', { name: 'Change' })).toBeTruthy();
    expect(screen.getByRole('cell', { name: '+12%' })).toBeTruthy();
  });
});
