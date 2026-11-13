import { DumbbellCard } from '../charts/DumbbellCard';
import { ChartCard } from '../charts/ChartCard';
import type { LineSeries } from '../charts/LineChart';
import type { Rollup } from '../data/rollup';
import { flagName } from '../data/flagNames';
import { flagMoves, openBySeverity, topOpenKinds, weeklyPoints, type FlagSeverityChoice } from '../data/offSeries';
import { useResource } from '../data/resource';
import type { DayPoint } from '../data/series';
import { offOpenFlags, offWeekly, type OffOpenFlagRow, type OffWeeklyRow } from '../data/siteData';
import { formatCompact, formatCount, formatDay } from '../format';
import { changeWords } from '../gallery/charts';
import { Segmented, useChoice } from './pageParts';

const HIDDEN = 'fewer than 5';

const known = (points: DayPoint[]) => points.filter((p) => p.value !== null) as { day: string; value: number }[];

/** "from 4,379,600 on 29 Mar 2026 to 4,887,851 on 1 Nov 2026, up 12%": the first and the newest known value of a series. */
export function firstToLast(points: DayPoint[], unit: string): string {
  const k = known(points);
  if (k.length < 2) return 'There are not yet enough weeks to compare.';
  const first = k[0];
  const last = k[k.length - 1];
  const words = changeWords(last.value, first.value);
  return `${formatCount(last.value)} ${unit} on ${formatDay(last.day)}, against ${formatCount(first.value)} on ${formatDay(first.day)} (${words}).`;
}

/** The newest week against the one before it. */
export function lastWeekWords(points: DayPoint[], what: string): string {
  const last = points[points.length - 1];
  const before = points[points.length - 2];
  if (!last || !before || last.value === null) return `There is no figure for ${what} in the newest week.`;
  const prior = before.value === null ? '' : ` (${changeWords(last.value, before.value)} on the week before)`;
  return `In the week ending ${formatDay(last.day)}, ${formatCount(last.value)} ${what}${prior}.`;
}

function busiest(points: DayPoint[]): { day: string; value: number } | null {
  const k = known(points);
  return k.length === 0 ? null : k.reduce((best, p) => (p.value > best.value ? p : best));
}

const LINE_A = { marker: 'circle', color: 'var(--primary)' } as const;
const LINE_B = { marker: 'triangle', dash: '6 4', color: 'var(--secondary)' } as const;

const week = { nativeGrain: 'week' as const, rowHeading: 'Week ending', pagerNoun: 'weeks', unknownText: HIDDEN, axisFormat: formatCompact, format: formatCount };

/** The first weeks hold OFF's big changes of March and early April (over a million products edited in one week against about 30,000 in an ordinary one), which squash every later week. */
export const RECENT_FROM = '2026-04-19';
export type RangeChoice = 'all' | 'recent';

function Charts({ weekly, open }: { weekly: OffWeeklyRow[]; open: OffOpenFlagRow[] }) {
  const [severity, setSeverity] = useChoice<FlagSeverityChoice>('offflags', ['all', 'error']);
  const [range, setRange] = useChoice<RangeChoice>('offrange', ['all', 'recent']);
  const shown = range === 'recent' ? weekly.filter((r) => r.weekEnd >= RECENT_FROM) : weekly;
  const held = weeklyPoints(weekly, (r) => r.productsHeld);
  const added = weeklyPoints(shown, (r) => r.productsAdded);
  const removed = weeklyPoints(shown, (r) => r.productsRemoved);
  const edited = weeklyPoints(shown, (r) => r.productsEdited);
  const ended = flagMoves(shown, 'ended', severity);
  const appeared = flagMoves(shown, 'appeared', severity);
  const errors = openBySeverity(open, 'error');
  const warnings = openBySeverity(open, 'warning');
  const info = openBySeverity(open, 'info');
  const kinds = topOpenKinds(open, 8);
  const peak = busiest(edited);

  const severityLabel = severity === 'error' ? 'error flags' : 'flags';
  const series = (id: string, label: string, points: DayPoint[], style: Pick<LineSeries, 'marker' | 'dash' | 'color'>, rollup: Rollup): LineSeries => ({ id, label, points, rollup, ...style });

  return (
    <>
      <div className="chart-section__head">
        <p className="chart-section__note">The three weekly charts below can leave out the first weeks, when Open Food Facts made very large changes.</p>
        <Segmented
          label="Which weeks to show"
          value={range}
          onChange={setRange}
          options={[
            { id: 'all', label: 'All weeks' },
            { id: 'recent', label: 'From 19 April' },
          ]}
        />
      </div>
    <div className="chart-grid chart-grid--two">
      <ChartCard
        {...week}
        title="Products in Open Food Facts"
        note="All the products OFF listed at each weekly snapshot, whether or not PackSense holds them."
        series={[series('held', 'Products', held, LINE_A, 'last')]}
        caption={firstToLast(held, 'products')}
      />
      <ChartCard
        {...week}
        form="columns"
        title="Products added and removed each week"
        note="Products that appear in one snapshot and not the one before (up), and products that disappear (down). A product that was moved or merged can show as removed."
        series={[series('added', 'Added', added, LINE_A, 'sum'), { ...series('removed', 'Removed', removed, LINE_B, 'sum'), below: true, color: 'var(--series-2)' }]}
        caption={`${lastWeekWords(added, 'products were added')} ${lastWeekWords(removed, 'were removed').replace(/^In the week ending [^,]+, /, 'In the same week, ')}`}
      />
      <ChartCard
        {...week}
        rollNote="In months, a product edited in two weeks is counted once in each, so a month's total is edits of products, not different products."
        form="columns"
        title="Products edited each week"
        note="Products whose last-edited time changed between two snapshots. A very busy week can come from one large automated change; the file does not say who edited."
        series={[series('edited', 'Products edited', edited, LINE_A, 'sum')]}
        caption={peak ? `${lastWeekWords(edited, 'products were edited')} The busiest week was the one ending ${formatDay(peak.day)}, with ${formatCount(peak.value)}.` : 'No figures yet.'}
      />
      <div className="chart-stack">
        <Segmented
          label="Which flags to count"
          value={severity}
          onChange={setSeverity}
          options={[
            { id: 'all', label: 'All flags' },
            { id: 'error', label: 'Errors only' },
          ]}
        />
        <ChartCard
          {...week}
          title="Flags that appeared and flags that ended each week"
          note={`${severity === 'error' ? 'Error flags only. ' : 'Every severity added up. '}A flag counts as ended when it left a product that is still listed and no other flag of the same kind took its place. Counts of 1 to 4 are left out.`}
          series={[series('appeared', 'Appeared', appeared, LINE_A, 'sum'), series('ended', 'Ended', ended, LINE_B, 'sum')]}
          caption={`${lastWeekWords(appeared, `${severityLabel} appeared`)} ${lastWeekWords(ended, `${severityLabel} ended`).replace(/^In the week ending [^,]+, /, 'In the same week, ')}`}
        />
      </div>
      <ChartCard
        {...week}
        rowHeading="Snapshot date"
        title="Open error flags across Open Food Facts"
        note="Flags that Open Food Facts marks as errors, open on any product at each snapshot."
        series={[series('errors', 'Open errors', errors, LINE_A, 'last')]}
        caption={firstToLast(errors, 'open error flags')}
      />
      <ChartCard
        {...week}
        rowHeading="Snapshot date"
        form="area"
        title="Open warning and information flags"
        note="Warnings (bottom) and information flags (on top, stacked), open at each snapshot, so the top edge is the two together. Most of them are about data that Open Food Facts works out itself. Errors have their own chart above."
        series={[series('warnings', 'Warnings', warnings, LINE_A, 'last'), { ...series('info', 'Information', info, LINE_B, 'last'), color: 'var(--series-2)' }]}
        caption={firstToLast(warnings, 'open warning flags')}
      />
      {kinds && (
        <DumbbellCard
          title={`Kinds of flag with the most open flags, ${formatDay(kinds.newest)}`}
          note={`The eight largest kinds, any severity, on ${formatDay(kinds.oldest)} (hollow dot) and on ${formatDay(kinds.newest)} (filled dot). Flags are counted, not products.`}
          fromLabel={formatDay(kinds.oldest)}
          toLabel={formatDay(kinds.newest)}
          format={formatCompact}
          caption={kinds.kinds.length > 0 ? `The largest kind of flag has ${formatCount(kinds.kinds[0].now)} open flags: "${flagName(`en:${kinds.kinds[0].kind}`).name}"` : undefined}
          rows={kinds.kinds.map((k) => ({
            id: `${k.severity}-${k.kind}`,
            label: flagName(`en:${k.kind}`).name,
            small: `${k.severity === 'error' ? 'Error' : k.severity === 'warning' ? 'Warning' : 'Information'}`,
            from: k.first,
            to: k.now,
          }))}
          valueHeading="Open flags"
          unknownText={HIDDEN}
        />
      )}
    </div>
    </>
  );
}

/** 'Across all of OFF': the whole of Open Food Facts week by week, from OFF's own weekly snapshots. It does not depend on the market choice. */
export function OffSection({ introHtml }: { introHtml: string | null }) {
  const weekly = useResource(offWeekly);
  const open = useResource(offOpenFlags);
  return (
    <section className="chart-section" aria-labelledby="across-off" data-focus="section:across-off">
      <h2 id="across-off">Across all of Open Food Facts</h2>
      {introHtml && <div className="prose" dangerouslySetInnerHTML={{ __html: introHtml }} />}
      {weekly.phase === 'ready' && open.phase === 'ready' ? (
        <Charts weekly={weekly.data} open={open.data} />
      ) : weekly.phase === 'error' || open.phase === 'error' ? (
        <p className="data-problem" role="status">These figures could not be loaded just now. Please try again in a little while.</p>
      ) : (
        <p className="data-loading" role="status">Loading the figures…</p>
      )}
    </section>
  );
}
