import { scaleLinear } from 'd3-scale';
import { useId, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Tip, type TipData } from './Tip';
import { useChartBox } from './useChartBox';

export interface WaterfallStep {
  id: string;
  label: string;
  /** A second line under the label ("1 Oct 2026"). */
  sub?: string;
  /** For a total, its value; for a change, how much it adds (positive) or takes away (negative). */
  value: number;
  total: boolean;
  /** One sentence saying what the step stands for, shown in the tip. */
  meaning: string;
}

export interface WaterfallCardProps {
  title: string;
  note?: ReactNode;
  caption?: string;
  steps: WaterfallStep[];
  /** The full number, for the tip, the readout and the table. */
  format: (value: number) => string;
  /** A short number for the axis and above the bars. */
  short: (value: number) => string;
  /** What the totals count ("Open flags"). */
  valueHeading: string;
  headingLevel?: 2 | 3 | 4;
}

/** The running total after each step: a total restarts it, a change moves it. */
export function runningTotals(steps: WaterfallStep[]): number[] {
  const totals: number[] = [];
  let run = 0;
  for (const step of steps) {
    run = step.total ? step.value : run + step.value;
    totals.push(run);
  }
  return totals;
}

/** The lowest value the axis shows: zero, unless every total stays above half the highest, when it starts a little below the lowest so the steps can be seen. */
export function axisFloor(lowest: number, highest: number): number {
  if (lowest <= highest * 0.5) return 0;
  const range = highest - lowest;
  const raw = Math.max(lowest - Math.max(range * 0.25, highest * 0.02), 0);
  const magnitude = 10 ** Math.floor(Math.log10(Math.max(raw, 1)));
  return Math.floor(raw / magnitude) * magnitude;
}

const signed = (value: number, format: (v: number) => string) => `${value < 0 ? '−' : '+'}${format(Math.abs(value))}`;

/**
 * How a total changes, step by step: where it began, what was added and taken away, where it ended. When every total stays high the axis
 * starts above zero so the steps can be seen, and the card says so and draws a break in the axis. Point at a bar, or use the arrow keys, for what the step means.
 */
export function WaterfallCard({ title, note, caption, steps, format, short, valueHeading, headingLevel = 3 }: WaterfallCardProps) {
  const id = useId();
  const { ref, width, unit } = useChartBox();
  const Heading = `h${headingLevel}` as 'h2' | 'h3' | 'h4';
  const [active, setActive] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);

  const totals = runningTotals(steps);
  const tops = steps.map((s, i) => (s.total ? s.value : Math.max(totals[i], totals[i] - s.value)));
  const bottoms = steps.map((s, i) => (s.total ? 0 : Math.min(totals[i], totals[i] - s.value)));
  const highest = Math.max(1, ...tops);
  const lowest = Math.min(...steps.filter((s) => s.total).map((s) => s.value), ...bottoms.filter((_, i) => !steps[i].total));
  const floor = axisFloor(lowest, highest);
  const cut = floor > 0;
  const height = Math.round(Math.min(Math.max(width * 0.45, unit * 14), unit * 20));
  const margin = { top: unit * 1.5, right: unit * 0.5, bottom: unit * 0.75, left: unit * 3.5 };
  const plotWidth = Math.max(width - margin.left - margin.right, 10);
  const plotHeight = Math.max(height - margin.top - margin.bottom, 10);
  const y = scaleLinear().domain([floor, highest]).nice(4).range([plotHeight, 0]);
  const [axisLow] = y.domain();
  const slot = plotWidth / steps.length;
  const barWidth = Math.min(slot * 0.62, unit * 4.5);
  const yOf = (value: number) => y(Math.max(value, axisLow));

  const move = (next: number | null) => setActive(next === null ? null : Math.min(Math.max(next, 0), steps.length - 1));
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'ArrowRight') move((active ?? -1) + 1);
    else if (event.key === 'ArrowLeft') move((active ?? steps.length) - 1);
    else if (event.key === 'Home') move(0);
    else if (event.key === 'End') move(steps.length - 1);
    else if (event.key === 'Escape') move(null);
    else return;
    event.preventDefault();
  };
  const describe = (i: number) => {
    const s = steps[i];
    return `${s.label}${s.sub ? ` ${s.sub}` : ''}: ${s.total ? `${valueHeading} ${format(s.value)}` : `${signed(s.value, format)}, running total ${format(totals[i])}`}. ${s.meaning}`;
  };
  const tip: TipData | null =
    active === null
      ? null
      : {
          x: margin.left + active * slot + slot / 2,
          y: margin.top + Math.min(yOf(tops[active]), plotHeight),
          title: `${steps[active].label}${steps[active].sub ? ` ${steps[active].sub}` : ''}`,
          lines: steps[active].total
            ? [{ label: valueHeading, value: format(steps[active].value) }]
            : [
                { label: 'Change', value: signed(steps[active].value, format) },
                { label: 'Running total', value: format(totals[active]) },
              ],
          note: steps[active].meaning,
        };

  return (
    <figure className="chart-card waterfall-card">
      <figcaption>
        <Heading>{title}</Heading>
        {note && <p className="chart-card__note">{note}</p>}
      </figcaption>
      <div
        className="chart waterfall"
        ref={ref}
        tabIndex={0}
        role="group"
        aria-label={`${title}. ${steps.map((s) => `${s.label}${s.sub ? ` ${s.sub}` : ''} ${s.total ? format(s.value) : signed(s.value, format)}`).join(', ')}. Use the left and right arrow keys to read it step by step.`}
        aria-describedby={`${id}-readout`}
        onKeyDown={onKey}
        onBlur={() => move(null)}
      >
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
          <g transform={`translate(${margin.left},${margin.top})`}>
            {y.ticks(4).map((tick) => (
              <g key={tick} transform={`translate(0,${y(tick)})`}>
                <line className="chart__grid" x1={0} x2={plotWidth} />
                <text className="chart__tick" x={-unit * 0.5} dy="0.32em" textAnchor="end">{short(tick)}</text>
              </g>
            ))}
            {cut && <path className="waterfall__break" d={`M ${-unit * 0.6} ${plotHeight - unit * 0.5} l ${unit * 0.4} ${-unit * 0.3} l ${unit * 0.4} ${unit * 0.6} l ${unit * 0.4} ${-unit * 0.3}`} fill="none" />}
            {steps.map((step, i) => {
              const top = yOf(tops[i]);
              const bottom = yOf(bottoms[i]);
              const x = i * slot + (slot - barWidth) / 2;
              const rise = !step.total && step.value >= 0;
              return (
                <g key={step.id} className={`waterfall__step${active === i ? ' waterfall__step--active' : ''}`} onPointerMove={() => setActive(i)} onPointerLeave={() => setActive(null)}>
                  <rect className="waterfall__hit" x={i * slot} y={0} width={slot} height={plotHeight} fill="transparent" />
                  <rect
                    className={`waterfall__bar waterfall__bar--${step.total ? 'total' : rise ? 'up' : 'down'}`}
                    x={x}
                    y={top}
                    width={barWidth}
                    height={Math.max(bottom - top, 2)}
                    rx={2}
                  />
                  <text className="chart__tick waterfall__value" x={x + barWidth / 2} y={top - unit * 0.4} textAnchor="middle">
                    {step.total ? short(step.value) : signed(step.value, short)}
                  </text>
                  {i < steps.length - 1 && <line className="waterfall__link" x1={x + barWidth} x2={(i + 1) * slot + (slot - barWidth) / 2} y1={yOf(totals[i])} y2={yOf(totals[i])} />}
                </g>
              );
            })}
          </g>
        </svg>
        <ol className="waterfall__labels" style={{ marginInlineStart: margin.left, marginInlineEnd: margin.right, gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }} aria-hidden="true">
          {steps.map((step, i) => (
            <li key={step.id}>
              <span className="waterfall__no">{i + 1}</span>
              <span className="waterfall__name">
                {step.label}
                {step.sub && <small>{step.sub}</small>}
              </span>
            </li>
          ))}
        </ol>
        <ol className="waterfall__key">
          {steps.map((step) => (
            <li key={step.id}>
              {step.label}
              {step.sub ? `, ${step.sub}` : ''}
            </li>
          ))}
        </ol>
        <Tip tip={tip} width={width} />
        <p id={`${id}-readout`} className="chart__readout" aria-live="polite">{active === null ? '' : describe(active)}</p>
      </div>
      {cut && <p className="chart-card__window">The scale starts at {short(axisLow)}, not at zero, so the steps can be seen. The heights of the two totals do not show how big they are; the numbers on the bars are the real ones.</p>}
      {caption && <p className="chart-card__caption">{caption}</p>}
      <button type="button" className="button button--quiet" aria-expanded={asTable} aria-controls={`${id}-table`} onClick={() => setAsTable((open) => !open)}>
        {asTable ? 'Hide the table' : 'Show as a table'}
      </button>
      <div id={`${id}-table`} hidden={!asTable}>
        {asTable && (
          <div className="table-card table-card--plain">
            <table>
              <caption className="visually-hidden">{title}</caption>
              <thead>
                <tr>
                  <th scope="col">Step</th>
                  <th scope="col">Change</th>
                  <th scope="col">Running total</th>
                </tr>
              </thead>
              <tbody>
                {steps.map((step, i) => (
                  <tr key={step.id}>
                    <th scope="row">{step.label}{step.sub ? ` ${step.sub}` : ''}</th>
                    <td data-label="Change">{step.total ? 'start or end' : signed(step.value, format)}</td>
                    <td data-label="Running total">{format(totals[i])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </figure>
  );
}
