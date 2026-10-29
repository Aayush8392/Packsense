import { useId, useState, type ReactNode } from 'react';
import { formatDay } from '../format';
import { LineChart, type LineSeries } from './LineChart';
import { Pager, pageWindow } from './Pager';

export interface ChartCardProps {
  title: string;
  /** One sentence under the title saying what is drawn and what is left out. */
  note?: ReactNode;
  series: LineSeries[];
  format: (value: number) => string;
  /** What a value that is not known is called in the table, for example "fewer than 5". */
  unknownText: string;
  compact?: boolean;
  headingLevel?: 2 | 3 | 4;
}

/**
 * A chart in a card, with a button that shows the very same numbers as a table. The table lists the newest day first, ten days to a
 * page, so it stays short however many days the data grows to. Each card opens and closes on its own.
 */
export function ChartCard({ title, note, series, format, unknownText, compact = false, headingLevel = 3 }: ChartCardProps) {
  const id = useId();
  const [asTable, setAsTable] = useState(false);
  const [page, setPage] = useState(0);
  const Heading = `h${headingLevel}` as 'h2' | 'h3' | 'h4';
  const days = series[0]?.points.map((p) => p.day) ?? [];
  const newestFirst = days.map((_, i) => days.length - 1 - i);
  const { start, end } = pageWindow(newestFirst.length, page);

  const toggle = () => {
    setPage(0);
    setAsTable((open) => !open);
  };

  return (
    <figure className={`chart-card${compact ? ' chart-card--compact' : ''}`}>
      <figcaption>
        <Heading>{title}</Heading>
        {note && <p className="chart-card__note">{note}</p>}
      </figcaption>
      <LineChart series={series} format={format} label={title} compact={compact} />
      <button type="button" className="button button--quiet" aria-expanded={asTable} aria-controls={`${id}-table`} onClick={toggle}>
        {asTable ? 'Hide the table' : 'Show as a table'}
      </button>
      <div id={`${id}-table`} hidden={!asTable}>
        {asTable && (
          <>
            <div className="table-card table-card--plain">
              <table>
                <caption className="visually-hidden">{title}, newest day first</caption>
                <thead>
                  <tr>
                    <th scope="col">Day</th>
                    {series.map((s) => <th key={s.id} scope="col">{s.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {newestFirst.slice(start, end).map((i) => (
                    <tr key={days[i]}>
                      <th scope="row">{formatDay(days[i])}</th>
                      {series.map((s) => (
                        <td key={s.id} data-label={s.label}>{s.points[i].value === null ? unknownText : format(s.points[i].value as number)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={newestFirst.length} page={page} onPage={setPage} noun="days" />
          </>
        )}
      </div>
    </figure>
  );
}
