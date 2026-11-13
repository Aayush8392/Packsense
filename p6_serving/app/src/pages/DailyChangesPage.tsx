import { ChartCard } from '../charts/ChartCard';
import type { LineSeries } from '../charts/LineChart';
import { ExternalLink } from '../components/ExternalLink';
import { Headline, LoadState, MarketSwitch, PageTitle, Panels, Segmented, TextPanel, pageSections, useChoice, useMarket } from '../components/pageParts';
import { pageBySlug } from '../content';
import example from '../data/indiaExample.json';
import { useResource } from '../data/resource';
import { JumpLink } from '../nav/JumpLink';
import { KINDS, changeDays, changeSeries, kindsOnDay, type DayPoint, type Scope } from '../data/series';
import { brandScorecard, categoryFitness, changeDaily, nutritionSources, qualityDaily, ruleChecks, type ChangeRow } from '../data/siteData';
import { ChartGallery } from '../gallery/ChartGallery';
import { formatCount, formatDay } from '../format';

const HIDDEN = 'fewer than 5';
const count = (value: number) => formatCount(value);
const show = (value: number | null) => (value === null ? HIDDEN : formatCount(value));

function lastValue(points: DayPoint[]): number | null {
  return points.length === 0 ? null : points[points.length - 1].value;
}

/** The kinds of edit on one day, as plain bars. The kinds overlap, so they are never added together and there is no total row. */
function KindsBars({ rows, scope, day }: { rows: ChangeRow[]; scope: Scope; day: string }) {
  const kinds = kindsOnDay(rows, scope, day);
  const widest = Math.max(1, ...kinds.map((k) => k.products ?? 0));
  return (
    <ul className="kind-bars">
      {kinds.map((kind) => (
        <li key={kind.group}>
          <span className="kind-bars__label">{kind.label}</span>
          <span className="kind-bars__track" aria-hidden="true">
            <span className="kind-bars__fill" style={{ width: `${((kind.products ?? 0) / widest) * 100}%` }} />
          </span>
          <span className="kind-bars__value">{kind.products === null ? HIDDEN : `at least ${formatCount(kind.products)}`}</span>
        </li>
      ))}
    </ul>
  );
}

function Main({ rows, market }: { rows: ChangeRow[]; market: Scope }) {
  const [view, setView] = useChoice<'timeline' | 'kinds'>('view', ['timeline', 'kinds']);
  const days = changeDays(rows, market);
  if (days.length === 0) return <p className="data-problem" role="status">There are no figures for this choice yet.</p>;
  const first = days[0];
  const last = days[days.length - 1];
  const edited = changeSeries(rows, market, 'any', days);
  const added = changeSeries(rows, market, 'new_product', days);

  const known = edited.filter((p) => p.value !== null) as { day: string; value: number }[];
  const busiest = known.reduce((best, p) => (p.value > best.value ? p : best), known[0] ?? { day: last, value: 0 });
  const facts = [
    { label: `Products edited, ${formatDay(last)} (at least)`, value: show(lastValue(edited)) },
    { label: `New products among them, ${formatDay(last)}`, value: show(lastValue(added)) },
    { label: 'Busiest day in this range (at least)', value: known.length === 0 ? HIDDEN : `${count(busiest.value)}, ${formatDay(busiest.day)}` },
  ];

  const timeline: LineSeries[] = [
    { id: 'edited', label: 'Products edited', points: edited, marker: 'circle', color: 'var(--primary)', rollup: 'sum' },
    { id: 'new', label: 'New products', points: added, marker: 'triangle', dash: '6 4', color: 'var(--secondary)', rollup: 'sum' },
  ];

  return (
    <>
      <Headline range={`${formatDay(first)} to ${formatDay(last)}, ${days.length} whole days`} facts={facts} />
      <p className="jump-line">
        <JumpLink to={`/explore/quality?${market === 'india' ? 'market=india&' : ''}focus=section:over-time`}>See the open flags on {formatDay(last)} in Data quality over time</JumpLink>
      </p>

      <section className="chart-section" aria-labelledby="edit-volume">
        <div className="chart-section__head">
          <h2 id="edit-volume" data-focus="section:edit-volume">Edits seen each day</h2>
          <Segmented
            label="Chart view"
            value={view}
            onChange={setView}
            options={[
              { id: 'timeline', label: 'Products edited and new' },
              { id: 'kinds', label: 'Work by kind' },
            ]}
          />
        </div>
        {view === 'timeline' ? (
          <ChartCard
            title="Products edited, and how many were new"
            note="Each day is counted at least; new products are counted among the products edited."
            series={timeline}
            rollNote={EDIT_ROLL_NOTE}
            format={count}
            unknownText={HIDDEN}
            headingLevel={3}
          />
        ) : (
          <>
            <p className="chart-section__note">One edit can touch several kinds, so the kinds overlap and are never added together. Each chart has its own scale.</p>
            <div className="chart-grid chart-grid--four">
              {KINDS.map((kind) => (
                <ChartCard
                  key={kind.group}
                  compact
                  headingLevel={3}
                  title={kind.label}
                  series={[{ id: kind.group, label: kind.label, points: changeSeries(rows, market, kind.group, days), marker: 'circle', color: 'var(--primary)', rollup: 'sum' }]}
                  rollNote={EDIT_ROLL_NOTE}
                  format={count}
                  unknownText={HIDDEN}
                />
              ))}
            </div>
          </>
        )}
      </section>

      <section className="chart-section" aria-labelledby="kinds-today">
        <h2 id="kinds-today">Work by kind of edit, {formatDay(last)}</h2>
        <div className="table-card table-card--figures">
          <table>
            <caption className="visually-hidden">Products edited on {formatDay(last)}, by kind of edit. The kinds overlap and are not added up.</caption>
            <thead>
              <tr>
                <th scope="col">Kind of edit</th>
                <th scope="col">Products edited (at least)</th>
              </tr>
            </thead>
            <tbody>
              {kindsOnDay(rows, market, last).map((kind) => (
                <tr key={kind.group}>
                  <th scope="row">{kind.label}</th>
                  <td data-label="Products edited (at least)">{show(kind.products)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

/** "Today in India": the newest complete day's counts, its kinds, the days before it, and one labelled real example product. */
function IndiaToday({ rows }: { rows: ChangeRow[] }) {
  const page = pageBySlug('india-today');
  const { intro, sections } = pageSections('india-today');
  const days = changeDays(rows, 'india');
  if (!page || days.length === 0) return null;
  const last = days[days.length - 1];
  const edited = changeSeries(rows, 'india', 'any', days);
  const added = changeSeries(rows, 'india', 'new_product', days);
  const recent = days.slice(-7).reverse();
  const at = (points: DayPoint[], day: string) => points[days.indexOf(day)]?.value ?? null;

  return (
    <section className="india-today" aria-labelledby="india-heading">
      <h2 id="india-heading">Today in India</h2>
      <p className="india-today__day">Newest complete day: {formatDay(last)}</p>
      <p className="jump-line"><JumpLink to="/get-the-data">Download the India data</JumpLink></p>
      <h3>{page.heading}</h3>
      <div className="prose" dangerouslySetInnerHTML={{ __html: intro }} />

      <div className="india-today__grid">
        <div>
          <dl className="india-today__counts">
            <div>
              <dt>Products edited (at least)</dt>
              <dd>{show(at(edited, last))}</dd>
            </div>
            <div>
              <dt>New products</dt>
              <dd>{show(at(added, last))}</dd>
            </div>
          </dl>
          <h4>Kinds of edit, {formatDay(last)}</h4>
          <KindsBars rows={rows} scope="india" day={last} />
        </div>

        <div>
          <h4>The days before</h4>
          <div className="table-card table-card--figures">
            <table>
              <caption className="visually-hidden">Products edited and new products in India on the last seven days</caption>
              <thead>
                <tr>
                  <th scope="col">Day</th>
                  <th scope="col">Products edited (at least)</th>
                  <th scope="col">New products</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((day) => (
                  <tr key={day}>
                    <th scope="row">{formatDay(day)}</th>
                    <td data-label="Products edited (at least)">{show(at(edited, day))}</td>
                    <td data-label="New products">{show(at(added, day))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <aside className="example" aria-labelledby="example-heading">
            <h4 id="example-heading">An example product</h4>
            <p className="example__label">A real Indian product, shown as an example. It is not necessarily one of today's edits.</p>
            <p className="example__name">{example.name}</p>
            <p className="example__brand">{example.brand}</p>
            <p className="example__links">
              <JumpLink to={`/look-up?barcode=${example.barcode}`}>Look it up on PackSense</JumpLink>
              <ExternalLink href={example.offUrl}>See it on Open Food Facts</ExternalLink>
            </p>
          </aside>
        </div>
      </div>

      {sections.map((section, i) => (
        <TextPanel key={section.title} id={`india-panel-${i}`} landmark={false} title={section.title} html={section.html} />
      ))}
    </section>
  );
}

const EDIT_ROLL_NOTE = 'In weeks and months, a product edited on two days is counted once on each of them, so these totals are edits of products, not different products.';
export function DailyChangesPage() {
  const loaded = useResource(changeDaily);
  const quality = useResource(qualityDaily);
  const brands = useResource(brandScorecard);
  const categories = useResource(categoryFitness);
  const rules = useResource(ruleChecks);
  const sources = useResource(nutritionSources);
  const [market, setMarket] = useMarket();
  const { intro, sections } = pageSections('daily-changes');

  return (
    <div className="data-page">
      <PageTitle slug="daily-changes" />
      <div className="prose" dangerouslySetInnerHTML={{ __html: intro }} />
      <MarketSwitch market={market} onChange={setMarket} />
      {loaded.phase === 'ready' ? (
        <>
          <Main rows={loaded.data} market={market} />
          <IndiaToday rows={loaded.data} />
          {quality.phase === 'ready' && brands.phase === 'ready' && [categories, rules, sources].every((r) => r.phase === 'ready' || r.phase === 'error') && (
            <ChartGallery
              data={{
                change: loaded.data,
                quality: quality.data,
                brands: brands.data,
                categories: categories.phase === 'ready' ? categories.data : undefined,
                rules: rules.phase === 'ready' ? rules.data : undefined,
                sources: sources.phase === 'ready' ? sources.data : undefined,
              }}
              market={market}
            />
          )}
        </>
      ) : (
        <LoadState loaded={[loaded]} />
      )}
      <Panels>
        {sections.map((section, i) => (
          <TextPanel key={section.title} id={`changes-panel-${i}`} title={section.title} html={section.html} />
        ))}
      </Panels>
    </div>
  );
}
