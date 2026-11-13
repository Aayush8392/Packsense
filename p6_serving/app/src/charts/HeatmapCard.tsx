import { useId, useMemo, useState, type KeyboardEvent, type ReactNode } from 'react';
import { addDays, formatDay } from '../format';
import type { DayPoint } from '../data/series';
import { heatCuts, heatGrid, heatLevel, heatOpacity, weekday } from './heat';
import type { LineSeries } from './LineChart';
import { SeriesTable } from './SeriesTable';
import { Tip, type TipData } from './Tip';
import { useChartBox } from './useChartBox';
import { clampStart } from './window';

const ROWS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const GAP = 3;
const WANTED_CELL = 24;

export interface HeatmapCardProps {
  title: string;
  note?: ReactNode;
  caption?: string;
  /** One point a day, from the first day to the last. */
  points: DayPoint[];
  /** What a point counts, for the tip and the table ("Products edited"). */
  label: string;
  format: (value: number) => string;
  unknownText: string;
  headingLevel?: 2 | 3 | 4;
}

function shortDate(iso: string): string {
  return formatDay(iso).slice(0, -5);
}

/**
 * A calendar of days: one square a day, a column a week (Monday first), darker meaning more. The number is written in the square when it fits, and
 * the tip, the keyboard readout and the table give it for every day. A long history is shown a window of weeks at a time.
 */
export function HeatmapCard({ title, note, caption, points, label, format, unknownText, headingLevel = 3 }: HeatmapCardProps) {
  const id = useId();
  const { ref, width, unit } = useChartBox();
  const Heading = `h${headingLevel}` as 'h2' | 'h3' | 'h4';
  const [active, setActive] = useState<string | null>(null);
  const [from, setFrom] = useState<number | null>(null);

  const byDay = useMemo(() => new Map(points.map((p) => [p.day, p.value])), [points]);
  const firstDay = points[0]?.day;
  const lastDay = points[points.length - 1]?.day;
  const grid = useMemo(() => (firstDay && lastDay ? heatGrid(firstDay, lastDay) : null), [firstDay, lastDay]);
  const cuts = useMemo(() => heatCuts(points.map((p) => p.value).filter((v): v is number => v !== null)), [points]);
  if (!grid || !firstDay || !lastDay) return null;

  const left = unit * 2.75;
  const top = unit * 1.5;
  const room = Math.max(width - left - unit * 0.5, 10);
  const fit = Math.max(1, Math.floor(room / (WANTED_CELL + GAP)));
  const shown = Math.min(grid.weeks.length, fit);
  const first = clampStart(from ?? grid.weeks.length - shown, grid.weeks.length, shown);
  const cell = Math.min(Math.floor(room / shown) - GAP, unit * 2.4);
  const visibleWeeks = grid.weeks.slice(first, first + shown);
  const height = top + 7 * (cell + GAP);
  const labelEvery = Math.max(1, Math.ceil((unit * 3.2) / (cell + GAP)));
  const levels = cuts.length + 1;

  const describe = (iso: string): TipData | null => {
    const { col, row } = grid.place(iso);
    const visibleCol = col - first;
    if (visibleCol < 0 || visibleCol >= shown) return null;
    const value = byDay.get(iso);
    return {
      x: left + visibleCol * (cell + GAP) + cell / 2,
      y: top + row * (cell + GAP),
      title: `${WEEKDAY_NAMES[row]} ${formatDay(iso)}`,
      lines: [{ label, value: value === null || value === undefined ? unknownText : format(value) }],
    };
  };
  const move = (iso: string | null) => {
    if (iso === null) return setActive(null);
    const next = iso < firstDay ? firstDay : iso > lastDay ? lastDay : iso;
    setActive(next);
    const col = grid.place(next).col;
    if (col < first) setFrom(col);
    else if (col >= first + shown) setFrom(col - shown + 1);
  };
  const onKey = (event: KeyboardEvent) => {
    const at = active ?? lastDay;
    if (event.key === 'ArrowLeft') move(addDays(at, -7));
    else if (event.key === 'ArrowRight') move(addDays(at, 7));
    else if (event.key === 'ArrowUp') move(addDays(at, -1));
    else if (event.key === 'ArrowDown') move(addDays(at, 1));
    else if (event.key === 'Home') move(firstDay);
    else if (event.key === 'End') move(lastDay);
    else if (event.key === 'Escape') move(null);
    else return;
    event.preventDefault();
  };

  const tip = active === null ? null : describe(active);
  const readout = active === null ? '' : `${WEEKDAY_NAMES[weekday(active)]} ${formatDay(active)}: ${label} ${byDay.get(active) == null ? unknownText : format(byDay.get(active) as number)}`;
  const legend = Array.from({ length: levels }, (_, level) => {
    const lo = level === 0 ? null : cuts[level - 1];
    const hi = level === levels - 1 ? null : cuts[level];
    const words = lo === null ? (hi === null ? 'every day' : `under ${format(hi)}`) : hi === null ? `${format(lo)} or more` : `${format(lo)} to under ${format(hi)}`;
    return { level, words };
  });
  const series: LineSeries[] = [{ id: 'days', label, points, marker: 'square', color: 'var(--primary)' }];

  return (
    <figure className="chart-card heatmap-card">
      <figcaption>
        <Heading>{title}</Heading>
        {note && <p className="chart-card__note">{note}</p>}
      </figcaption>
      {grid.weeks.length > shown && (
        <div className="chart-card__controls">
          <button type="button" className="button button--quiet" disabled={first === 0} onClick={() => setFrom(clampStart(first - Math.max(1, Math.floor(shown / 2)), grid.weeks.length, shown))}>
            Earlier
          </button>
          <button type="button" className="button button--quiet" disabled={first + shown >= grid.weeks.length} onClick={() => setFrom(clampStart(first + Math.max(1, Math.floor(shown / 2)), grid.weeks.length, shown))}>
            Later
          </button>
          <span className="chart-card__window">Weeks beginning {shortDate(visibleWeeks[0])} to {shortDate(visibleWeeks[visibleWeeks.length - 1])}.</span>
        </div>
      )}
      <div
        className="chart heatmap"
        ref={ref}
        tabIndex={0}
        role="group"
        aria-label={`${title}. One square a day from ${formatDay(firstDay)} to ${formatDay(lastDay)}, a column a week. Use the arrow keys to read it day by day.`}
        aria-describedby={`${id}-readout`}
        onKeyDown={onKey}
        onBlur={() => move(null)}
      >
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
          {ROWS.map((name, row) => (
            <text key={name} className="chart__tick" x={left - unit * 0.5} y={top + row * (cell + GAP) + cell / 2} dy="0.32em" textAnchor="end">{name}</text>
          ))}
          {visibleWeeks.map((monday, col) =>
            col % labelEvery === 0 ? (
              <text key={monday} className="chart__tick" x={left + col * (cell + GAP) + cell / 2} y={top - unit * 0.5} textAnchor="middle">{shortDate(monday)}</text>
            ) : null,
          )}
          {visibleWeeks.flatMap((monday, col) =>
            ROWS.map((_, row) => {
              const iso = addDays(monday, row);
              if (iso < firstDay || iso > lastDay) return null;
              const value = byDay.get(iso);
              const x = left + col * (cell + GAP);
              const y = top + row * (cell + GAP);
              const level = value === null || value === undefined ? -1 : heatLevel(value, cuts);
              const dark = level >= 0 && heatOpacity(level, levels) >= 0.75;
              return (
                <g key={iso} className={`heatmap__cell${active === iso ? ' heatmap__cell--active' : ''}`} onPointerMove={() => setActive(iso)} onPointerLeave={() => setActive(null)}>
                  <rect
                    x={x}
                    y={y}
                    width={cell}
                    height={cell}
                    rx={3}
                    fill={level < 0 ? 'none' : 'var(--primary)'}
                    fillOpacity={level < 0 ? 1 : heatOpacity(level, levels)}
                    stroke={level < 0 ? 'var(--fg-muted)' : 'none'}
                    strokeDasharray={level < 0 ? '3 3' : undefined}
                  />
                  {cell >= unit * 1.6 && (
                    <text x={x + cell / 2} y={y + cell / 2} dy="0.34em" textAnchor="middle" className="heatmap__number" fill={dark ? 'var(--bg)' : 'var(--fg)'}>
                      {value === null || value === undefined ? '?' : format(value)}
                    </text>
                  )}
                </g>
              );
            }),
          )}
        </svg>
        <Tip tip={tip} width={width} />
        <p id={`${id}-readout`} className="chart__readout" aria-live="polite">{readout}</p>
        <ul className="chart__legend heatmap__legend">
          {legend.map(({ level, words }) => (
            <li key={level}>
              <svg width={unit * 1.4} height={unit * 1.1} viewBox="0 0 10 8" aria-hidden="true" focusable="false">
                <rect width="10" height="8" rx="2" fill="var(--primary)" fillOpacity={heatOpacity(level, levels)} />
              </svg>
              <span>{words}</span>
            </li>
          ))}
          <li>
            <svg width={unit * 1.4} height={unit * 1.1} viewBox="0 0 10 8" aria-hidden="true" focusable="false">
              <rect x="0.5" y="0.5" width="9" height="7" rx="2" fill="none" stroke="var(--fg-muted)" strokeDasharray="2 2" />
            </svg>
            <span>{unknownText}</span>
          </li>
        </ul>
      </div>
      {caption && <p className="chart-card__caption">{caption}</p>}
      <SeriesTable title={title} series={series} format={format} unknownText={unknownText} />
    </figure>
  );
}

