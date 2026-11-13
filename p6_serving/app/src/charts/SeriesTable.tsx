import { useId, useState } from 'react';
import type { Grain } from '../data/rollup';
import { GRAIN_WORDS } from '../data/rollup';
import { formatPeriod } from '../format';
import type { LineSeries } from './LineChart';
import { PadRows, Pager, padCount, pageWindow } from './Pager';

export interface SeriesTableProps {
  title: string;
  series: LineSeries[];
  format: (value: number) => string;
  /** What a value that is not known is called in the table, for example "fewer than 5". */
  unknownText: string;
  grain?: Grain;
  /** The first column's heading and what the pages count (default from the grain: "Day" and "days"). */
  heading?: string;
  noun?: string;
}

/**
 * The very same numbers as a chart, as a table, behind a button: the newest first, ten rows to a page, so it stays short however long the data
 * grows. Give it a `key` that changes with the grain so it starts on the first page again.
 */
export function SeriesTable({ title, series, format, unknownText, grain = 'day', heading, noun }: SeriesTableProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);
  const word = GRAIN_WORDS[grain];
  const days = series[0]?.points.map((p) => p.day) ?? [];
  const newestFirst = days.map((_, i) => days.length - 1 - i);
  const { start, end } = pageWindow(newestFirst.length, page);

  return (
    <>
      <button
        type="button"
        className="button button--quiet"
        aria-expanded={open}
        aria-controls={`${id}-table`}
        onClick={() => {
          setPage(0);
          setOpen((o) => !o);
        }}
      >
        {open ? 'Hide the table' : 'Show as a table'}
      </button>
      <div id={`${id}-table`} hidden={!open}>
        {open && (
          <>
            <div className="table-card table-card--plain table-card--paged">
              <table>
                <caption className="visually-hidden">{title}, newest {word.one} first</caption>
                <thead>
                  <tr>
                    <th scope="col">{heading ?? word.heading}</th>
                    {series.map((s) => <th key={s.id} scope="col">{s.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {newestFirst.slice(start, end).map((i) => (
                    <tr key={days[i]}>
                      <th scope="row">{formatPeriod(days[i], grain)}{series[0].points[i].partial ? ' (part)' : ''}</th>
                      {series.map((s) => (
                        <td key={s.id} data-label={s.label}>{s.points[i].value === null ? unknownText : format(s.points[i].value as number)}</td>
                      ))}
                    </tr>
                  ))}
                  <PadRows count={padCount(newestFirst.length, end - start)} columns={series.length + 1} />
                </tbody>
              </table>
            </div>
            <Pager total={newestFirst.length} page={page} onPage={setPage} noun={noun ?? word.many} />
          </>
        )}
      </div>
    </>
  );
}
