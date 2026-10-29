import { scaleLinear } from 'd3-scale';
import { line, symbol, symbolCircle, symbolDiamond, symbolSquare, symbolTriangle } from 'd3-shape';
import { useId, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { formatDay } from '../format';
import type { DayPoint } from '../data/series';
import { useChartBox } from './useChartBox';

export type MarkerKind = 'circle' | 'diamond' | 'triangle' | 'square';

export interface LineSeries {
  id: string;
  label: string;
  points: DayPoint[];
  /** Series differ by marker and line style as well as colour, so a chart never relies on colour alone. */
  marker: MarkerKind;
  dash?: string;
  /** A CSS colour (a token such as var(--primary)). */
  color: string;
}

export interface LineChartProps {
  series: LineSeries[];
  format: (value: number) => string;
  /** Names the chart for a screen reader. */
  label: string;
  compact?: boolean;
}

const SYMBOLS = { circle: symbolCircle, diamond: symbolDiamond, triangle: symbolTriangle, square: symbolSquare };

export function markerPath(kind: MarkerKind, size: number): string {
  return symbol(SYMBOLS[kind], size)() ?? '';
}

function shortDay(iso: string): string {
  return formatDay(iso).slice(0, -5);
}

/** Every Nth day gets a label, so about six fit. */
export function tickStep(count: number, wanted = 6): number {
  return Math.max(1, Math.ceil(count / wanted));
}

/** A one-sentence description of the chart for a screen reader: each series from its first to its last known value. */
export function describeSeries(series: LineSeries[], format: (value: number) => string): string {
  return series
    .map((s) => {
      const known = s.points.filter((p) => p.value !== null) as { day: string; value: number }[];
      if (known.length === 0) return `${s.label}: no values`;
      const first = known[0];
      const last = known[known.length - 1];
      return `${s.label}: ${format(first.value)} on ${formatDay(first.day)}, ${format(last.value)} on ${formatDay(last.day)}`;
    })
    .join('. ');
}

export function LineChart({ series, format, label, compact = false }: LineChartProps) {
  const { ref, width, unit } = useChartBox();
  const id = useId();
  const [active, setActive] = useState<number | null>(null);

  const days = series[0]?.points.map((p) => p.day) ?? [];
  const count = days.length;
  const height = compact ? Math.round(unit * 10) : Math.round(Math.min(Math.max(width * 0.42, unit * 14), unit * 22));
  const margin = { top: unit, right: unit * 1.25, bottom: unit * 2.25, left: unit * (compact ? 3 : 3.75) };
  const plotWidth = Math.max(width - margin.left - margin.right, 10);
  const plotHeight = Math.max(height - margin.top - margin.bottom, 10);

  const maxValue = Math.max(0, ...series.flatMap((s) => s.points.map((p) => p.value ?? 0)));
  const y = scaleLinear().domain([0, maxValue === 0 ? 1 : maxValue]).nice(4).range([plotHeight, 0]);
  const x = scaleLinear().domain([0, Math.max(count - 1, 1)]).range([0, plotWidth]);
  const yTicks = y.ticks(compact ? 3 : 4);
  const step = tickStep(count, compact ? 4 : 6);
  const path = line<DayPoint & { i: number }>()
    .defined((p) => p.value !== null)
    .x((p) => x(p.i))
    .y((p) => y(p.value as number));

  const move = (next: number | null) => setActive(next === null ? null : Math.min(Math.max(next, 0), count - 1));
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'ArrowRight') move((active ?? -1) + 1);
    else if (event.key === 'ArrowLeft') move((active ?? count) - 1);
    else if (event.key === 'Home') move(0);
    else if (event.key === 'End') move(count - 1);
    else if (event.key === 'Escape') move(null);
    else return;
    event.preventDefault();
  };
  const onPointer = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width === 0) return;
    move(Math.round(((event.clientX - box.left) / box.width) * (count - 1)));
  };

  const readout =
    active === null
      ? ''
      : `${formatDay(days[active])}: ${series.map((s) => `${s.label} ${s.points[active].value === null ? 'not known' : format(s.points[active].value as number)}`).join(', ')}`;

  return (
    <div
      className={`chart${compact ? ' chart--compact' : ''}`}
      ref={ref}
      tabIndex={0}
      role="group"
      aria-label={`${label}. ${describeSeries(series, format)}. Use the left and right arrow keys to read it day by day.`}
      aria-describedby={`${id}-readout`}
      onKeyDown={onKey}
      onBlur={() => move(null)}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
        <g transform={`translate(${margin.left},${margin.top})`}>
          {yTicks.map((tick) => (
            <g key={tick} transform={`translate(0,${y(tick)})`}>
              <line className="chart__grid" x1={0} x2={plotWidth} />
              <text className="chart__tick" x={-unit * 0.5} dy="0.32em" textAnchor="end">{format(tick)}</text>
            </g>
          ))}
          {days.map((day, i) =>
            i % step === 0 ? (
              <text key={day} className="chart__tick" x={x(i)} y={plotHeight + unit * 1.5} textAnchor="middle">{shortDay(day)}</text>
            ) : null,
          )}
          {series.map((s) => (
            <g key={s.id} style={{ color: s.color }}>
              <path
                className="chart__line"
                d={path(s.points.map((p, i) => ({ ...p, i }))) ?? ''}
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeDasharray={s.dash}
              />
              {s.points.map((p, i) =>
                p.value !== null && (count <= 31 || i === active || i === count - 1) ? (
                  <path key={p.day} className="chart__marker" d={markerPath(s.marker, compact ? 28 : 44)} transform={`translate(${x(i)},${y(p.value)})`} fill="currentColor" />
                ) : null,
              )}
            </g>
          ))}
          {active !== null && <line className="chart__cursor" x1={x(active)} x2={x(active)} y1={0} y2={plotHeight} />}
          <rect
            className="chart__hit"
            width={plotWidth}
            height={plotHeight}
            fill="transparent"
            onPointerMove={onPointer}
            onPointerLeave={() => move(null)}
          />
        </g>
      </svg>
      <p id={`${id}-readout`} className="chart__readout" aria-live="polite">{readout}</p>
      <ul className="chart__legend">
        {series.map((s) => (
          <li key={s.id} style={{ color: s.color }}>
            <svg width={unit * 2.5} height={unit} viewBox={`0 0 ${unit * 2.5} ${unit}`} aria-hidden="true" focusable="false">
              <line x1={0} x2={unit * 2.5} y1={unit / 2} y2={unit / 2} stroke="currentColor" strokeWidth={2} strokeDasharray={s.dash} />
              <path d={markerPath(s.marker, 44)} transform={`translate(${unit * 1.25},${unit / 2})`} fill="currentColor" />
            </svg>
            <span>{s.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
