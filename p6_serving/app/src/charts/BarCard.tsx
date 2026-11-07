import { useId, useState } from 'react';
import type { BarRow } from '../gallery/charts';

export interface BarCardProps {
  title: string;
  note?: string;
  /** A sentence written by code from the numbers, shown under the bars. */
  caption?: string;
  rows: BarRow[];
  valueHeading: string;
  /** What a value that is not known is called, for example "fewer than 5". */
  unknownText: string;
  headingLevel?: 2 | 3 | 4;
}

/** Where a value sits on a track that runs from the smallest value (or zero) to the largest (or zero), as percentages of the track. */
export function barBox(value: number, low: number, high: number): { left: number; width: number } {
  const span = high - low;
  if (span <= 0) return { left: 0, width: 0 };
  const zero = ((0 - low) / span) * 100;
  const at = ((value - low) / span) * 100;
  return { left: Math.min(zero, at), width: Math.abs(at - zero) };
}

/** Horizontal bars in a card, with a button that shows the very same numbers as a table. Values below zero run to the left of a centre line. */
export function BarCard({ title, note, caption, rows, valueHeading, unknownText, headingLevel = 3 }: BarCardProps) {
  const id = useId();
  const [asTable, setAsTable] = useState(false);
  const Heading = `h${headingLevel}` as 'h2' | 'h3' | 'h4';
  const known = rows.map((r) => r.value).filter((v): v is number => v !== null);
  const low = Math.min(0, ...known);
  const high = Math.max(0, ...known);
  const zeroAt = high - low > 0 ? ((0 - low) / (high - low)) * 100 : 0;

  return (
    <figure className="chart-card bar-card">
      <figcaption>
        <Heading>{title}</Heading>
        {note && <p className="chart-card__note">{note}</p>}
      </figcaption>
      <ul className="bar-chart" aria-label={title}>
        {rows.map((row) => {
          const box = row.value === null ? { left: 0, width: 0 } : barBox(row.value, low, high);
          return (
            <li key={row.id}>
              <span className="bar-chart__label">
                {row.label}
                {row.small && <small>{row.small}</small>}
              </span>
              <span className="bar-chart__track" aria-hidden="true">
                {low < 0 && <span className="bar-chart__zero" style={{ left: `${zeroAt}%` }} />}
                <span className={`bar-chart__fill${row.value !== null && row.value < 0 ? ' bar-chart__fill--down' : ''}`} style={{ left: `${box.left}%`, width: `${box.width}%` }} />
              </span>
              <span className="bar-chart__value">{row.value === null ? unknownText : row.display}</span>
            </li>
          );
        })}
      </ul>
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
                  <th scope="col">{valueHeading}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <th scope="row">{row.label}</th>
                    <td data-label={valueHeading}>{row.value === null ? unknownText : row.display}</td>
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
