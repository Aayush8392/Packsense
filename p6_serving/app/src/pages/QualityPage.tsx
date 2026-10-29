import { ChartCard } from '../charts/ChartCard';
import type { LineSeries } from '../charts/LineChart';
import { Headline, LoadState, MarketSwitch, PageTitle, Panels, TextPanel, pageSections, useMarket } from '../components/pageParts';
import { flagName } from '../data/flagNames';
import { useResource } from '../data/resource';
import { SEVERITIES, flagsPerProduct, productsHeld, qualityDays, topFamilies, type Scope } from '../data/series';
import { qualityDaily, type QualityRow } from '../data/siteData';
import { formatCount, formatDay, formatPerProduct as perProduct } from '../format';

/** How each severity is drawn: its own marker and line style as well as its own colour. */
const SEVERITY_STYLE: Record<string, Pick<LineSeries, 'marker' | 'dash' | 'color'>> = {
  error: { marker: 'diamond', color: 'var(--primary)' },
  warning: { marker: 'triangle', dash: '6 4', color: 'var(--secondary)' },
  info: { marker: 'circle', dash: '2 4', color: 'var(--fg-muted)' },
};

function Charts({ rows, market }: { rows: QualityRow[]; market: Scope }) {
  const days = qualityDays(rows, market);
  if (days.length === 0) return <p className="data-problem" role="status">There are no figures for this choice yet.</p>;
  const first = days[0];
  const last = days[days.length - 1];

  const total = flagsPerProduct(rows, market, 'all');
  const held = productsHeld(rows, market);
  const valueOn = (points: { day: string; value: number | null }[], day: string) => points.find((p) => p.day === day)?.value ?? null;
  const families = topFamilies(rows, market, last, 10);
  const anyOffNames = families.some((f) => !flagName(f.family).plain);

  const heldNow = valueOn(held, last);
  const facts = [
    { label: `Open flags per product held, ${formatDay(first)} (at least)`, value: perProduct(valueOn(total, first) ?? 0) },
    { label: `Open flags per product held, ${formatDay(last)} (at least)`, value: perProduct(valueOn(total, last) ?? 0) },
    { label: `Products held, ${formatDay(last)}`, value: heldNow === null ? 'not known' : formatCount(heldNow) },
  ];

  const severitySeries = (id: string): LineSeries => ({
    id,
    label: SEVERITIES.find((s) => s.id === id)?.label ?? id,
    points: flagsPerProduct(rows, market, id),
    ...SEVERITY_STYLE[id],
  });

  return (
    <>
      <Headline range={`${formatDay(first)} to ${formatDay(last)}, ${days.length} whole days`} facts={facts} />

      <section className="chart-section" aria-labelledby="over-time">
        <h2 id="over-time">Flags and products, day by day</h2>
        <div className="chart-grid chart-grid--two">
          <ChartCard
            title="Flags per product held"
            note="All open flags added up and divided by the products held that day. Flags with a count of 1 to 4 are left out of the sum."
            series={[{ id: 'total', label: 'Flags per product', points: total, marker: 'circle', color: 'var(--primary)' }]}
            format={perProduct}
            unknownText="not known"
          />
          <ChartCard
            title="Products held"
            note="How many products PackSense holds each day. When this rises, the flag total rises with it."
            series={[{ id: 'held', label: 'Products held', points: held, marker: 'square', color: 'var(--secondary)' }]}
            format={formatCount}
            unknownText="not known"
          />
        </div>
      </section>

      <section className="chart-section" aria-labelledby="by-severity">
        <h2 id="by-severity">By how serious the flag is</h2>
        <p className="chart-section__note">Each chart has its own scale. Errors, warnings and information are different markers and line styles.</p>
        <div className="chart-grid chart-grid--three">
          {SEVERITIES.map((s) => (
            <ChartCard
              key={s.id}
              compact
              headingLevel={3}
              title={s.label}
              series={[severitySeries(s.id)]}
              format={perProduct}
              unknownText="not known"
            />
          ))}
        </div>
      </section>

      <section className="chart-section" aria-labelledby="by-family">
        <h2 id="by-family">The most common kinds of flag, {formatDay(last)}</h2>
        {anyOffNames && (
          <p className="chart-section__note">Where no plain name is written yet, the name is Open Food Facts' own, made readable.</p>
        )}
        <div className="table-card table-card--figures">
          <table>
            <caption className="visually-hidden">The ten kinds of flag with the most open flags on {formatDay(last)}</caption>
            <thead>
              <tr>
                <th scope="col">Kind of flag</th>
                <th scope="col">How serious</th>
                <th scope="col">Open flags</th>
                <th scope="col">Share of all</th>
              </tr>
            </thead>
            <tbody>
              {families.map((f) => {
                const name = flagName(f.family);
                return (
                  <tr key={f.family}>
                    <th scope="row">
                      {name.name}
                      {!name.plain && f.family !== 'unmapped' && <small className="code"> {f.family}</small>}
                    </th>
                    <td data-label="How serious">{f.severities.map((id) => SEVERITIES.find((s) => s.id === id)?.label ?? id).join(', ')}</td>
                    <td data-label="Open flags">{formatCount(f.flags)}</td>
                    <td data-label="Share of all">{`${(f.share * 100).toFixed(1)}%`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

export function QualityPage() {
  const loaded = useResource(qualityDaily);
  const [market, setMarket] = useMarket();
  const { intro, sections } = pageSections('quality-over-time');

  return (
    <div className="data-page">
      <PageTitle slug="quality-over-time" />
      <div className="prose" dangerouslySetInnerHTML={{ __html: intro }} />
      <MarketSwitch market={market} onChange={setMarket} />
      {loaded.phase === 'ready' ? <Charts rows={loaded.data} market={market} /> : <LoadState loaded={[loaded]} />}
      <Panels>
        {sections.map((section, i) => (
          <TextPanel key={section.title} id={`quality-panel-${i}`} title={section.title} html={section.html} />
        ))}
      </Panels>
    </div>
  );
}
