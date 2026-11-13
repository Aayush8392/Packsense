import { scaleLinear } from 'd3-scale';
import { line, symbol, symbolCircle, symbolDiamond, symbolSquare, symbolTriangle } from 'd3-shape';
import { useId, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { GRAIN_WORDS, type Grain, type Parts, type Rollup } from '../data/rollup';
import { formatDay, formatPeriod } from '../format';
import type { DayPoint } from '../data/series';
import { Overview } from './Overview';
import { clampStart, fitDomain } from './window';
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
  /** How its points become weeks or months. A series without a rule is drawn at its own grain only. */
  rollup?: Rollup;
  /** The two sums of a ratio (rollup 'ratio'), aligned with `points`. */
  parts?: Parts;
}

export interface LineChartProps {
  series: LineSeries[];
  format: (value: number) => string;
  /** Names the chart for a screen reader. */
  label: string;
  compact?: boolean;
  /** What one point is (default a day); it words the ticks, the readout and the screen-reader text. */
  grain?: Grain;
  /** How many points are in view and which one is the first. Without `size` every point is drawn; without `start` the newest are shown. */
  size?: number;
  start?: number;
  onStart?: (start: number) => void;
  /** Counts start at zero (the default). A rate or a share may start higher when its values stay close together. */
  zeroBase?: boolean;
}

const SYMBOLS = { circle: symbolCircle, diamond: symbolDiamond, triangle: symbolTriangle, square: symbolSquare };

export function markerPath(kind: MarkerKind, size: number): string {
  return symbol(SYMBOLS[kind], size)() ?? '';
}

function shortDay(iso: string, grain: Grain): string {
  return grain === 'month' ? formatPeriod(iso, grain).slice(0, 3) + ' ' + iso.slice(2, 4) : formatDay(iso).slice(0, -5);
}

/** Every Nth day gets a label, so about six fit. */
export function tickStep(count: number, wanted = 6): number {
  return Math.max(1, Math.ceil(count / wanted));
}

/** A one-sentence description of the chart for a screen reader: each series from its first to its last known value. */
export function describeSeries(series: LineSeries[], format: (value: number) => string, grain: Grain = 'day'): string {
  return series
    .map((s) => {
      const known = s.points.filter((p) => p.value !== null) as { day: string; value: number }[];
      if (known.length === 0) return `${s.label}: no values`;
      const first = known[0];
      const last = known[known.length - 1];
      return `${s.label}: ${format(first.value)} on ${formatPeriod(first.day, grain)}, ${format(last.value)} on ${formatPeriod(last.day, grain)}`;
    })
    .join('. ');
}

export function LineChart({ series, format, label, compact = false, grain = 'day', size, start, onStart, zeroBase = true }: LineChartProps) {
  const { ref, width, unit } = useChartBox();
  const id = useId();
  const [active, setActive] = useState<number | null>(null);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const drag = useRef<{ x: number; start: number; moved: boolean } | null>(null);

  const allDays = series[0]?.points.map((p) => p.day) ?? [];
  const total = allDays.length;
  const shown = size === undefined ? total : Math.min(size, total);
  const canPan = shown < total && onStart !== undefined;
  const first = clampStart(start ?? total - shown, total, shown);
  const slice = <T,>(items: T[]): T[] => items.slice(first, first + shown);
  const days = slice(allDays);
  const count = days.length;
  const visible = series.map((s) => ({ ...s, points: slice(s.points) }));

  const height = compact ? Math.round(unit * 10) : Math.round(Math.min(Math.max(width * 0.42, unit * 14), unit * 22));
  const margin = { top: unit, right: unit * 1.25, bottom: unit * 2.25, left: unit * (compact ? 3 : 3.75) };
  const plotWidth = Math.max(width - margin.left - margin.right, 10);
  const plotHeight = Math.max(height - margin.top - margin.bottom, 10);

  // While a window is being dragged the axis stays as it was; it fits the new view when the drag ends.
  const fitAt = dragFrom ?? first;
  const [low, high] = fitDomain(series.flatMap((s) => s.points.slice(fitAt, fitAt + shown).map((p) => p.value)), zeroBase);
  const y = scaleLinear().domain([low, high]).nice(4).range([plotHeight, 0]);
  const x = scaleLinear().domain([0, Math.max(count - 1, 1)]).range([0, plotWidth]);
  const yTicks = y.ticks(compact ? 3 : 4);
  const step = tickStep(count, compact ? 4 : 6);
  const path = line<DayPoint & { i: number }>()
    .defined((p) => p.value !== null)
    .x((p) => x(p.i))
    .y((p) => y(p.value as number));

  const move = (next: number | null) => setActive(next === null ? null : Math.min(Math.max(next, 0), count - 1));
  const pan = (by: number) => {
    if (canPan) onStart(clampStart(first + by, total, shown));
  };
  const onKey = (event: KeyboardEvent) => {
    if (event.shiftKey && (event.key === 'ArrowRight' || event.key === 'ArrowLeft')) pan((event.key === 'ArrowRight' ? 1 : -1) * Math.max(1, Math.floor(shown / 4)));
    else if (event.key === 'ArrowRight') move((active ?? -1) + 1);
    else if (event.key === 'ArrowLeft') move((active ?? count) - 1);
    else if (event.key === 'Home') move(0);
    else if (event.key === 'End') move(count - 1);
    else if (event.key === 'Escape') move(null);
    else return;
    event.preventDefault();
  };
  const hover = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width === 0) return;
    move(Math.round(((event.clientX - box.left) / box.width) * (count - 1)));
  };
  const onDown = (event: PointerEvent<SVGRectElement>) => {
    if (!canPan) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drag.current = { x: event.clientX, start: first, moved: false };
  };
  const onMove = (event: PointerEvent<SVGRectElement>) => {
    const d = drag.current;
    if (!d || !canPan) return hover(event);
    const dx = event.clientX - d.x;
    if (!d.moved && Math.abs(dx) < 6) return hover(event);
    if (!d.moved) {
      d.moved = true;
      setDragFrom(d.start);
      move(null);
    }
    const perPoint = plotWidth / Math.max(shown - 1, 1);
    onStart(clampStart(d.start - Math.round(dx / perPoint), total, shown));
  };
  const onUp = () => {
    drag.current = null;
    setDragFrom(null);
  };

  const word = GRAIN_WORDS[grain].one;
  const partialAt = (i: number) => series[0].points[first + i]?.partial === true;
  const readout =
    active === null
      ? ''
      : `${formatPeriod(days[active], grain)}${partialAt(active) ? ` (not a whole ${word})` : ''}: ${visible.map((s) => `${s.label} ${s.points[active].value === null ? 'not known' : format(s.points[active].value as number)}`).join(', ')}`;
  const span = count === 0 ? '' : ` Showing ${formatPeriod(days[0], grain)} to ${formatPeriod(days[count - 1], grain)}.`;

  return (
    <div
      className={`chart${compact ? ' chart--compact' : ''}`}
      ref={ref}
      tabIndex={0}
      role="group"
      aria-label={`${label}. ${describeSeries(visible, format, grain)}.${span} Use the left and right arrow keys to read it ${word} by ${word}${canPan ? ', and shift with the arrow keys to move earlier or later' : ''}.`}
      aria-describedby={`${id}-readout`}
      onKeyDown={onKey}
      onBlur={() => move(null)}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false" className={canPan ? 'chart__svg--pan' : undefined}>
        <g transform={`translate(${margin.left},${margin.top})`}>
          {yTicks.map((tick) => (
            <g key={tick} transform={`translate(0,${y(tick)})`}>
              <line className="chart__grid" x1={0} x2={plotWidth} />
              <text className="chart__tick" x={-unit * 0.5} dy="0.32em" textAnchor="end">{format(tick)}</text>
            </g>
          ))}
          {days.map((day, i) =>
            i % step === 0 ? (
              <text key={day} className="chart__tick" x={x(i)} y={plotHeight + unit * 1.5} textAnchor="middle">{shortDay(day, grain)}</text>
            ) : null,
          )}
          {visible.map((s) => (
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
                  <path
                    key={p.day}
                    className="chart__marker"
                    d={markerPath(s.marker, compact ? 28 : 44)}
                    transform={`translate(${x(i)},${y(p.value)})`}
                    fill={p.partial ? 'var(--card)' : 'currentColor'}
                    stroke="currentColor"
                    strokeWidth={p.partial ? 1.5 : 0}
                  />
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
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={onUp}
            onPointerLeave={() => {
              if (!drag.current) move(null);
            }}
          />
        </g>
      </svg>
      {canPan && <Overview series={series} first={first} shown={shown} width={width} unit={unit} onStart={(next) => onStart(next)} />}
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
