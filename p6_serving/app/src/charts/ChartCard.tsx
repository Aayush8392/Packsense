import { useId, useMemo, useState, type ReactNode } from 'react';
import { GRAIN_WORDS, MIN_BUCKETS, grainsFrom, rollUp, type Grain } from '../data/rollup';
import { Segmented } from '../components/pageParts';
import { formatPeriod } from '../format';
import { LineChart, type ChartForm, type LineSeries } from './LineChart';
import { clampStart, windowSize } from './window';
import { PadRows, Pager, padCount, pageWindow } from './Pager';

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
  /** A sentence written by code from the numbers, shown under the chart. */
  caption?: string;
  /** A shorter way to write a number on the chart itself (axis, hover, screen-reader text); the table keeps `format`. */
  axisFormat?: (value: number) => string;
  /** The first column of the table at the chart's own grain: "Day" for daily data, "Week ending" for weekly data. */
  rowHeading?: string;
  /** What the table pages count at the chart's own grain: "days" or "weeks". */
  pagerNoun?: string;
  /** What one point of `series` is. Weeks and months are offered only for series that say how they roll up. */
  nativeGrain?: Grain;
  /** Counts start at zero (the default); a rate or a share may start higher when its values stay close together. */
  zeroBase?: boolean;
  /** One sentence shown under the controls when the view is weeks or months: what a total of days means for this chart. */
  rollNote?: string;
  /** How the points are drawn (default a line); columns and stacked areas keep the window, the views and the tip of a line chart. */
  form?: ChartForm;
}

/**
 * A chart in a card, with a button that shows the very same numbers as a table. The table lists the newest first, ten rows to a
 * page, so it stays short however many days the data grows to. Each card opens and closes on its own.
 */
export function ChartCard({ title, note, series: own, format, unknownText, compact = false, headingLevel = 3, caption, axisFormat, rowHeading, pagerNoun, nativeGrain = 'day', zeroBase = true, rollNote, form = 'line' }: ChartCardProps) {
  const id = useId();
  const [asTable, setAsTable] = useState(false);
  const [page, setPage] = useState(0);
  const [chosen, setChosen] = useState<Grain>(nativeGrain);
  const [from, setFrom] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);
  const Heading = `h${headingLevel}` as 'h2' | 'h3' | 'h4';

  const rolls = useMemo(() => {
    const canRoll = own.length > 0 && own.every((s) => s.rollup !== undefined);
    const by = new Map<Grain, LineSeries[]>();
    for (const g of grainsFrom(nativeGrain)) {
      if (g === nativeGrain) by.set(g, own);
      else if (canRoll) {
        const rolled = own.map((s) => ({ ...s, points: rollUp(s.points, nativeGrain, g, s.rollup!, s.parts) }));
        if ((rolled[0]?.points.length ?? 0) >= MIN_BUCKETS) by.set(g, rolled);
      }
    }
    return by;
  }, [own, nativeGrain]);
  const grains = [...rolls.keys()];
  const grain = rolls.has(chosen) ? chosen : nativeGrain;
  const series = rolls.get(grain) ?? own;
  const days = series[0]?.points.map((p) => p.day) ?? [];
  const word = GRAIN_WORDS[grain];
  const atNative = grain === nativeGrain;
  const heading = atNative && rowHeading ? rowHeading : word.heading;
  const noun = atNative && pagerNoun ? pagerNoun : word.many;
  const recent = windowSize(grain, compact);
  const size = showAll ? days.length : Math.min(recent, days.length);
  const first = clampStart(from ?? days.length - size, days.length, size);
  const canPan = size < days.length;
  const hasPartial = series.some((s) => s.points.some((p) => p.partial));
  const changeGrain = (next: Grain) => {
    setChosen(next);
    setFrom(null);
    setShowAll(false);
    setPage(0);
  };
  const pan = (by: number) => setFrom(clampStart(first + by, days.length, size));
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
      {(grains.length > 1 || days.length > recent) && (
        <div className="chart-card__controls">
          {grains.length > 1 && (
            <Segmented
              label="How much time each point covers"
              value={grain}
              onChange={changeGrain}
              options={grains.map((g) => ({ id: g, label: GRAIN_WORDS[g].many.replace(/^./, (c) => c.toUpperCase()) }))}
            />
          )}
          {days.length > recent && (
            <>
              <button type="button" className="button button--quiet" disabled={!canPan || first === 0} onClick={() => pan(-Math.max(1, Math.floor(size / 2)))}>
                Earlier
              </button>
              <button type="button" className="button button--quiet" disabled={!canPan || first + size >= days.length} onClick={() => pan(Math.max(1, Math.floor(size / 2)))}>
                Later
              </button>
              <button
                type="button"
                className="button button--quiet"
                aria-pressed={showAll}
                onClick={() => {
                  setShowAll((all) => !all);
                  setFrom(null);
                }}
              >
                {showAll ? `Show the latest ${recent} ${word.many}` : `Show all ${days.length} ${word.many}`}
              </button>
            </>
          )}
        </div>
      )}
      {!atNative && rollNote && <p className="chart-card__window">{rollNote}</p>}
      {canPan && (
        <p className="chart-card__window">
          Showing {formatPeriod(days[first], grain)} to {formatPeriod(days[first + size - 1], grain)}. Drag the chart, or use the buttons, to move.
        </p>
      )}
      <LineChart series={series} format={axisFormat ?? format} label={title} compact={compact} grain={grain} size={size} start={first} onStart={setFrom} zeroBase={zeroBase} form={form} />
      {hasPartial && <p className="chart-card__window">A hollow point covers only part of its {word.one}.</p>}
      {caption && <p className="chart-card__caption">{caption}</p>}
      <button type="button" className="button button--quiet" aria-expanded={asTable} aria-controls={`${id}-table`} onClick={toggle}>
        {asTable ? 'Hide the table' : 'Show as a table'}
      </button>
      <div id={`${id}-table`} hidden={!asTable}>
        {asTable && (
          <>
            <div className="table-card table-card--plain table-card--paged">
              <table>
                <caption className="visually-hidden">{title}, newest {word.one} first</caption>
                <thead>
                  <tr>
                    <th scope="col">{heading}</th>
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
            <Pager total={newestFirst.length} page={page} onPage={setPage} noun={noun} />
          </>
        )}
      </div>
    </figure>
  );
}
