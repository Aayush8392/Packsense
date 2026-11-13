import { scaleLinear } from 'd3-scale';
import { useId, useState, type ReactNode } from 'react';
import { Tip, type TipData } from './Tip';

export interface DumbbellRow {
  id: string;
  label: string;
  /** A small line under the label (a severity, a tag). */
  small?: string;
  /** The value at the start and at the end; null when a value is not known (hidden on purpose). */
  from: number | null;
  to: number | null;
}

export interface DumbbellCardProps {
  title: string;
  note?: ReactNode;
  caption?: string;
  /** What the two ends are called: a date such as "22 Mar 2026". */
  fromLabel: string;
  toLabel: string;
  /** What the values count, for the tip and the table ("Open flags"). */
  valueHeading: string;
  rows: DumbbellRow[];
  format: (value: number) => string;
  unknownText: string;
  headingLevel?: 2 | 3 | 4;
}

/** "+11%", "−4%" or "no change": the change from one end to the other, as a share of where it began. */
export function changeShare(from: number, to: number): string {
  if (from === 0) return to === 0 ? 'no change' : 'up from none';
  const share = Math.round(((to - from) / from) * 100);
  return share === 0 ? 'no change' : `${share > 0 ? '+' : '−'}${Math.abs(share)}%`;
}

/**
 * Before and after for each row: a hollow dot where it began and a filled dot where it is now, joined by a line, all on one scale. The scale
 * starts below the lowest value, not at zero, so the moves can be seen; it says so under the dots. Point at a row, or tab to it, for the figures.
 */
export function DumbbellCard({ title, note, caption, fromLabel, toLabel, valueHeading, rows, format, unknownText, headingLevel = 3 }: DumbbellCardProps) {
  const id = useId();
  const Heading = `h${headingLevel}` as 'h2' | 'h3' | 'h4';
  const [asTable, setAsTable] = useState(false);
  const [tip, setTip] = useState<{ index: number; at: TipData } | null>(null);
  const [boxWidth, setBoxWidth] = useState(640);

  const known = rows.flatMap((r) => [r.from, r.to]).filter((v): v is number => v !== null);
  const scale = scaleLinear()
    .domain([known.length ? Math.min(...known) : 0, known.length ? Math.max(...known) : 1])
    .nice(4);
  const [low, high] = scale.domain();
  const place = (value: number) => (high === low ? 50 : ((value - low) / (high - low)) * 100);
  const ticks = scale.ticks(4);

  const describe = (row: DumbbellRow, el: HTMLElement, clientX: number): TipData => {
    const list = el.parentElement;
    const box = list ? list.getBoundingClientRect() : null;
    if (box) setBoxWidth(box.width);
    return {
      x: box ? clientX - box.left : 0,
      y: el.offsetTop + el.offsetHeight / 2,
      title: row.label,
      lines: [
        { label: fromLabel, value: row.from === null ? unknownText : format(row.from) },
        { label: toLabel, value: row.to === null ? unknownText : format(row.to) },
        ...(row.from !== null && row.to !== null ? [{ label: 'Change', value: `${row.to >= row.from ? '+' : '−'}${format(Math.abs(row.to - row.from))} (${changeShare(row.from, row.to)})` }] : []),
      ],
      note: row.small,
    };
  };

  return (
    <figure className="chart-card dumbbell-card">
      <figcaption>
        <Heading>{title}</Heading>
        {note && <p className="chart-card__note">{note}</p>}
      </figcaption>
      <div className="bar-chart-wrap">
        <ul className="dumbbell" aria-label={title}>
          {rows.map((row, index) => {
            const both = row.from !== null && row.to !== null;
            return (
              <li
                key={row.id}
                tabIndex={0}
                aria-label={`${row.label}: ${row.from === null ? unknownText : format(row.from)} on ${fromLabel}, ${row.to === null ? unknownText : format(row.to)} on ${toLabel}${both ? `, ${changeShare(row.from as number, row.to as number)}` : ''}`}
                onPointerMove={(event) => setTip({ index, at: describe(row, event.currentTarget, event.clientX) })}
                onPointerLeave={() => setTip(null)}
                onFocus={(event) => {
                  const box = event.currentTarget.getBoundingClientRect();
                  setTip({ index, at: describe(row, event.currentTarget, box.left + box.width / 2) });
                }}
                onBlur={() => setTip(null)}
              >
                <span className="bar-chart__label">
                  {row.label}
                  {row.small && <small>{row.small}</small>}
                </span>
                <span className="dumbbell__track" aria-hidden="true">
                  {both && <span className="dumbbell__link" style={{ left: `${Math.min(place(row.from as number), place(row.to as number))}%`, width: `${Math.abs(place(row.to as number) - place(row.from as number))}%` }} />}
                  {row.from !== null && <span className="dumbbell__dot dumbbell__dot--from" style={{ left: `${place(row.from)}%` }} />}
                  {row.to !== null && <span className="dumbbell__dot dumbbell__dot--to" style={{ left: `${place(row.to)}%` }} />}
                </span>
                <span className="bar-chart__value">{row.to === null ? unknownText : both ? `${format(row.to)}, ${changeShare(row.from as number, row.to)}` : format(row.to)}</span>
              </li>
            );
          })}
          <li className="dumbbell__axis" aria-hidden="true">
            <span />
            <span className="dumbbell__ticks">
              {ticks.map((t) => (
                <span key={t} style={{ left: `${place(t)}%` }}>{format(t)}</span>
              ))}
            </span>
            <span />
          </li>
        </ul>
        <Tip tip={tip?.at ?? null} width={boxWidth} />
      </div>
      <p className="chart-card__window">
        <span className="dumbbell__key dumbbell__key--from" aria-hidden="true" /> {fromLabel} <span className="dumbbell__key dumbbell__key--to" aria-hidden="true" /> {toLabel}. The scale starts at {format(low)}, not at zero.
      </p>
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
                  <th scope="col">Name</th>
                  <th scope="col">{valueHeading}, {fromLabel}</th>
                  <th scope="col">{valueHeading}, {toLabel}</th>
                  <th scope="col">Change</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <th scope="row">{row.label}</th>
                    <td data-label={`${valueHeading}, ${fromLabel}`}>{row.from === null ? unknownText : format(row.from)}</td>
                    <td data-label={`${valueHeading}, ${toLabel}`}>{row.to === null ? unknownText : format(row.to)}</td>
                    <td data-label="Change">{row.from === null || row.to === null ? unknownText : changeShare(row.from, row.to)}</td>
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
