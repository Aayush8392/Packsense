import { Fragment, useId, useState, type MouseEvent } from 'react';
import { Clip, PadRows, Pager, padCount, pageWindow } from '../charts/Pager';
import { Headline, LoadState, MarketSwitch, PageTitle, Panels, TextPanel, pageSections, useMarket } from '../components/pageParts';
import {
  ITEMS, SORTS, bandLabel, bandOf, SPREAD_SORTS, brandsSentence, histogram, median, rankBrands, shareFilling, spreadLines, spreadSentence, visibleBrands, type Ranked, type SortId,
} from '../data/brands';
import { useResource } from '../data/resource';
import type { Scope } from '../data/series';
import { brandScorecard, type BrandRow } from '../data/siteData';
import { formatCount, formatDay } from '../format';
import { usePageState } from '../nav/pageState';

const percent = (share: number) => `${Math.round(share * 100)}%`;

/** Brands per half-point score band, drawn as one button per band: pressing a band shows only the brands in it. */
function Histogram({ counts, total, typical, band, onBand }: {
  counts: number[];
  total: number;
  typical: number;
  band: number | null;
  onBand: (next: number | null) => void;
}) {
  const id = useId();
  const [asTable, setAsTable] = useState(false);
  const tallest = Math.max(...counts, 1);
  const typicalBand = bandOf(typical);
  return (
    <section className="chart-card histogram" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>How the brands are spread</h2>
      <p className="chart-card__note">
        Each bar counts the brands whose score falls in a band of half a point. The typical brand fills {typical.toFixed(1)} of the 7 things. Press a bar to see only the brands in it.
      </p>
      <div className="histogram__bars" role="group" aria-label="Brands by score band">
        {counts.map((count, i) => (
          <button
            key={i}
            type="button"
            className={`histogram__bar${band === i ? ' histogram__bar--on' : ''}${i === typicalBand ? ' histogram__bar--typical' : ''}`}
            aria-pressed={band === i}
            aria-label={`Score ${bandLabel(i)}: ${count} ${count === 1 ? 'brand' : 'brands'}${i === typicalBand ? ', where the typical brand is' : ''}`}
            onClick={() => onBand(band === i ? null : i)}
          >
            <span className="histogram__fill" style={{ height: `${(count / tallest) * 100}%` }} aria-hidden="true" />
          </button>
        ))}
      </div>
      <div className="histogram__axis" aria-hidden="true">
        <span>0</span><span>1</span><span>2</span><span>3</span><span>4</span><span>5</span><span>6</span><span>7</span>
      </div>
      <p className="histogram__legend">The outlined bar holds the typical brand. The axis is the score, from 0 to 7.</p>
      <button type="button" className="button button--quiet" aria-expanded={asTable} aria-controls={`${id}-table`} onClick={() => setAsTable((open) => !open)}>
        {asTable ? 'Hide the table' : 'Show as a table'}
      </button>
      <div id={`${id}-table`} hidden={!asTable}>
        {asTable && (
          <div className="table-card table-card--plain">
            <table>
              <caption className="visually-hidden">Brands in each score band</caption>
              <thead>
                <tr><th scope="col">Score</th><th scope="col">Brands</th><th scope="col">Share of brands</th></tr>
              </thead>
              <tbody>
                {counts.map((count, i) => (
                  <tr key={i}>
                    <th scope="row">{bandLabel(i)}</th>
                    <td data-label="Brands">{count}</td>
                    <td data-label="Share of brands">{`${((count / total) * 100).toFixed(1)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

/** How complete one brand's products are: how many fill all seven things, six, and so on down to none. */
function BrandSpread({ row, titleId }: { row: BrandRow; titleId: string }) {
  const lines = spreadLines(row);
  if (!lines) return null;
  const tallest = Math.max(...lines.map((line) => line.products), 1);
  return (
    <>
      <h3 id={titleId} className="brand-expand__title">How complete the products of {row.name} are</h3>
      <p className="chart-section__note">{spreadSentence(row)} The score above is the average of these.</p>
      <ul className="brand-details__lines" aria-label={`Products of ${row.name} by how many of the 7 things they fill`}>
        {lines.map((line) => (
          <li key={line.filledCount}>
            <span className="brand-details__label">{line.filledCount === 7 ? 'All 7' : line.filledCount === 0 ? 'None' : `${line.filledCount} of 7`}</span>
            <span className="brand-details__bar" aria-hidden="true">
              {line.products > 0 && <span style={{ width: `${(line.products / tallest) * 100}%` }} />}
            </span>
            <span className="brand-details__count">{formatCount(line.products)} ({percent(line.share)})</span>
          </li>
        ))}
      </ul>
    </>
  );
}

function BrandTable({ entries, total, openName, onOpen, sort }: { entries: Ranked[]; total: number; openName: string | null; onOpen: ((name: string) => void) | null; sort: SortId }) {
  const atLeast = sort === 'full-share' ? 7 : sort === 'most-share' ? 5 : null;
  const shareLabel = atLeast === 7 ? 'Fill all 7' : 'Fill 5 or more';
  const prefix = useId();
  const columns = 4 + ITEMS.length + (atLeast !== null ? 1 : 0) + (onOpen ? 1 : 0);
  // A press anywhere on a row opens it, except on the button itself (which does the same) or on a link.
  const rowClick = (name: string) => (event: MouseEvent) => {
    if (!(event.target as HTMLElement).closest('button, a')) onOpen?.(name);
  };
  return (
    <div className="table-card table-card--figures table-card--brands table-card--paged">
      <table>
        <caption className="visually-hidden">Brands, with the share of their products that fill each of the seven things. Each row opens to show how complete that brand's products are.</caption>
        <thead>
          <tr>
            <th scope="col">Brand</th>
            <th scope="col">Place</th>
            <th scope="col">Products held</th>
            <th scope="col">Score (of 7)</th>
            {ITEMS.map((item) => <th key={item.key} scope="col">{item.label}</th>)}
            {atLeast !== null && <th scope="col">{shareLabel}</th>}
            {onOpen && <th scope="col">Its products</th>}
          </tr>
        </thead>
        <tbody>
          {entries.map(({ row, rank, score }, i) => {
            const open = openName === row.name;
            const panelId = `${prefix}-panel-${i}`;
            return (
              <Fragment key={row.name}>
                <tr className={onOpen ? 'brand-row brand-row--openable' : 'brand-row'} data-open={open} onClick={onOpen ? rowClick(row.name) : undefined}>
                  <th scope="row"><Clip>{row.name}</Clip></th>
                  <td data-label="Place">{rank}</td>
                  <td data-label="Products held">{formatCount(row.products)}</td>
                  <td data-label="Score (of 7)">{score.toFixed(1)}</td>
                  {ITEMS.map((item) => (
                    <td key={item.key} data-label={item.label}>{percent(row.filled[item.key] / row.products)}</td>
                  ))}
                  {atLeast !== null && <td data-label={shareLabel}>{percent(shareFilling(row, atLeast) ?? 0)}</td>}
                  {onOpen && (
                    <td data-label="Its products">
                      <button
                        type="button"
                        className="button button--quiet brand-toggle"
                        aria-expanded={open}
                        aria-controls={panelId}
                        aria-label={`Details for ${row.name}`}
                        onClick={() => onOpen(row.name)}
                      >
                        Details
                        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6" /></svg>
                      </button>
                    </td>
                  )}
                </tr>
                {onOpen && (
                  <tr className="brand-expand" data-open={open}>
                    <td colSpan={columns} id={panelId} role="region" aria-labelledby={`${panelId}-title`}>
                      <div className="brand-expand__panel">
                        <div className="brand-expand__inner" inert={!open}>
                          <div className="brand-expand__content">
                            <BrandSpread row={row} titleId={`${panelId}-title`} />
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
          <PadRows count={padCount(total, entries.length)} columns={columns} />
        </tbody>
      </table>
    </div>
  );
}

function Brands({ rows, market }: { rows: BrandRow[]; market: Scope }) {
  const ranked = rankBrands(rows, market);
  // The page's choices are kept for this tab: a refresh, or coming Back after a jump, finds them as they were.
  const [band, setBand] = usePageState<number | null>(`band-${market}`, null);
  const [query, setQuery] = usePageState(`query-${market}`, '');
  const [sort, setSort] = usePageState<SortId>(`sort-${market}`, 'score-high');
  const [page, setPage] = usePageState(`page-${market}`, 0);
  const [openName, setOpenName] = usePageState<string | null>(`open-${market}`, null);
  const searchId = useId();
  const sortId = useId();

  if (ranked.length === 0) return <p className="data-problem" role="status">There are no brands to rank for this choice yet.</p>;

  const shown = visibleBrands(ranked, band, query, sort);
  const { start, end } = pageWindow(shown.length, page);
  const counts = histogram(ranked);
  const typical = median(ranked.map((entry) => entry.score));
  const asOf = ranked[0].row.asOf;
  const hasDetails = ranked[0].row.spread !== null;
  // Changing what is listed goes back to the first page and closes the open row.
  const change = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    setPage(0);
    setOpenName(null);
  };

  return (
    <>
      <Headline
        range={`As of ${formatDay(asOf)}`}
        facts={[
          { label: 'Brands ranked', value: formatCount(ranked.length) },
          { label: 'Typical score (of 7)', value: typical.toFixed(1) },
          { label: 'Highest score', value: ranked[0].score.toFixed(1) },
        ]}
      />
      <p className="headline__sentence">{brandsSentence(ranked, market)}</p>

      <Histogram counts={counts} total={ranked.length} typical={typical} band={band} onBand={change(setBand)} />

      <section className="brand-list" aria-labelledby="brand-list-title">
        <h2 id="brand-list-title">The ranked brands</h2>
        <div className="brand-list__controls">
          <div className="field">
            <label htmlFor={searchId}>Find a brand</label>
            <input id={searchId} type="search" value={query} placeholder="For example nestle" autoComplete="off" onChange={(e) => change(setQuery)(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor={sortId}>Order by</label>
            <select id={sortId} value={sort} onChange={(e) => change(setSort)(e.target.value as SortId)}>
              {SORTS.filter((option) => hasDetails || !SPREAD_SORTS.includes(option.id)).map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
          </div>
        </div>
        {band !== null && (
          <p className="filter-chip">
            <span>Showing scores {bandLabel(band)}</span>
            <button type="button" className="button button--quiet" onClick={() => change(setBand)(null)}>Show all scores</button>
          </p>
        )}
        <p className="brand-list__count" role="status">
          {shown.length === ranked.length ? `All ${formatCount(shown.length)} brands` : `${formatCount(shown.length)} of ${formatCount(ranked.length)} brands`}
        </p>
        {shown.length === 0 ? (
          <p className="data-problem" role="status">No brand matches. Try another spelling, or show all scores.</p>
        ) : (
          <>
            <BrandTable
              entries={shown.slice(start, end)}
              total={shown.length}
              openName={openName}
              sort={sort}
              onOpen={hasDetails ? (name) => setOpenName(openName === name ? null : name) : null}
            />
            <Pager total={shown.length} page={page} onPage={(next) => { setPage(next); setOpenName(null); }} noun="brands" />
          </>
        )}
      </section>
    </>
  );
}

export function BrandsPage() {
  const loaded = useResource(brandScorecard);
  const [market, setMarket] = useMarket();
  const { intro, sections } = pageSections('brands');
  return (
    <div className="data-page">
      <PageTitle slug="brands" />
      <div className="prose" dangerouslySetInnerHTML={{ __html: intro }} />
      <MarketSwitch market={market} onChange={setMarket} />
      {loaded.phase === 'ready' ? <Brands key={market} rows={loaded.data} market={market} /> : <LoadState loaded={[loaded]} />}
      <Panels>
        {sections.map((section, i) => (
          <TextPanel key={section.title} id={`brands-panel-${i}`} title={section.title} html={section.html} />
        ))}
      </Panels>
    </div>
  );
}
