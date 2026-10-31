import { useId, useState } from 'react';
import { Clip, PAGE_SIZE, PadRows, Pager, padCount, pageWindow } from '../charts/Pager';
import { LoadState, PageTitle, Panels, Segmented, TextPanel, pageSections, useChoice } from '../components/pageParts';
import { useResource } from '../data/resource';
import {
  GOLD_VIEWS, doneRows, goldCell, rawRows, reasonFor, sameFieldRows, searchRows, showcase, silverRows,
  type GoldView, type ListRow, type Showcase, type ShowcaseProduct,
} from '../data/showcase';
import { signalFor } from '../data/signals';
import { formatCount } from '../format';

const KEYS = ['ordinary_food', 'several_flags', 'long_history', 'india'] as const;

function Flow({ product }: { product: ShowcaseProduct }) {
  const raw = Number(product.silver.counts.raw_top_level_fields ?? Object.keys(product.bronze.record).length);
  const columns = Object.keys(product.silver.row).length;
  const hidden = Number(product.silver.counts.silver_columns_hidden ?? 0);
  return (
    <ol className="flow" aria-label="The three steps">
      <li>
        <h3>Raw copy</h3>
        <p className="flow__name">bronze</p>
        <p>{formatCount(raw)} fields, exactly as they arrived.</p>
      </li>
      <li>
        <h3>Cleaned copy</h3>
        <p className="flow__name">silver</p>
        <p>{columns} columns, {hidden} of them hidden on purpose.</p>
      </li>
      <li>
        <h3>Tables for answers</h3>
        <p className="flow__name">gold</p>
        <p>{GOLD_VIEWS.length} tables, the ones this site is drawn from.</p>
      </li>
    </ol>
  );
}

function Switcher({ products, value, onChange }: { products: ShowcaseProduct[]; value: string; onChange: (next: string) => void }) {
  const ordered = KEYS.map((key) => products.find((p) => p.key === key)).filter((p): p is ShowcaseProduct => Boolean(p));
  return (
    <section className="switcher" aria-labelledby="switcher-title">
      <h2 id="switcher-title">Follow a real product</h2>
      <Segmented label="Product to follow" value={value} onChange={onChange} options={ordered.map((p) => ({ id: p.key, label: p.name.length > 28 ? `${p.name.slice(0, 26)}…` : p.name }))} />
      {ordered
        .filter((p) => p.key === value)
        .map((p) => (
          <p key={p.key} className="switcher__about">
            <strong>{p.name}</strong> (barcode {p.code}, brand {p.brand}). {reasonFor(p)}
          </p>
        ))}
    </section>
  );
}

function SameField({ product }: { product: ShowcaseProduct }) {
  const rows = sameFieldRows(product);
  return (
    <section className="chart-section" aria-labelledby="same-title">
      <h2 id="same-title">The same field, three steps</h2>
      <p className="chart-section__note">One fact about this product, as each step holds it.</p>
      <div className="table-card table-card--figures table-card--same">
        <table>
          <caption className="visually-hidden">Name, pack size, categories and energy of {product.name} in the raw copy, the cleaned copy and the tables</caption>
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Raw copy (bronze)</th>
              <th scope="col">Cleaned copy (silver)</th>
              <th scope="col">Tables (gold)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.field}>
                <th scope="row">{row.field}</th>
                <td data-label="Raw copy (bronze)">{row.raw}</td>
                <td data-label="Cleaned copy (silver)">{row.silver}</td>
                <td data-label="Tables (gold)">{row.gold}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

type Filter = 'all' | 'kept' | 'hidden';

/** A list of keys and values for one layer: searchable, paged ten at a time, long values opened on demand. The silver list can also be cut to what is kept or hidden. */
function Layer({ id, title, intro, rows, hiddenWord, withFilter, noun }: {
  id: string;
  title: string;
  intro: string;
  rows: ListRow[];
  hiddenWord: string;
  withFilter: boolean;
  noun: string;
}) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [page, setPage] = useState(0);
  const searchId = useId();
  const byFilter = rows.filter((row) => (filter === 'all' ? true : filter === 'hidden' ? row.hidden : !row.hidden));
  const shown = searchRows(byFilter, query);
  const { start, end } = pageWindow(shown.length, page);
  return (
    <section className="chart-section layer" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>{title}</h2>
      <p className="chart-section__note">{intro}</p>
      <div className="brand-list__controls">
        <div className="field">
          <label htmlFor={searchId}>Search the {noun}</label>
          <input id={searchId} type="search" value={query} autoComplete="off" onChange={(e) => { setQuery(e.target.value); setPage(0); }} />
        </div>
        {withFilter && (
          <Segmented
            label={`Which ${noun} to list`}
            value={filter}
            onChange={(next) => { setFilter(next); setPage(0); }}
            options={[{ id: 'all', label: `All ${rows.length}` }, { id: 'kept', label: 'Kept' }, { id: 'hidden', label: 'Hidden on purpose' }]}
          />
        )}
      </div>
      <p className="brand-list__count" role="status">
        {shown.length === rows.length ? `All ${formatCount(rows.length)} ${noun}` : `${formatCount(shown.length)} of ${formatCount(rows.length)} ${noun}`}
      </p>
      {shown.length === 0 ? (
        <p className="data-problem" role="status">Nothing matches. Try another word.</p>
      ) : (
        <>
          <dl className="kv">
            {shown.slice(start, end).map((row) => (
              <div key={row.key} className={row.hidden ? 'kv__row kv__row--hidden' : 'kv__row'}>
                <dt title={row.key}>{row.key}</dt>
                <dd>
                  {row.hidden ? (
                    <span className="kv__marker">{hiddenWord}</span>
                  ) : row.full ? (
                    <details>
                      <summary>{row.short}</summary>
                      <pre>{row.full}</pre>
                    </details>
                  ) : (
                    <span title={row.short}>{row.short}</span>
                  )}
                </dd>
              </div>
            ))}
            {Array.from({ length: padCount(shown.length, end - start) }, (_, i) => <div key={`pad-${i}`} className="kv__row kv__row--pad" aria-hidden="true" />)}
          </dl>
          <Pager total={shown.length} page={page} onPage={setPage} noun={noun} />
        </>
      )}
    </section>
  );
}

function GoldTableCard({ view, product }: { view: GoldView; product: ShowcaseProduct }) {
  const [page, setPage] = useState(0);
  const rows = product.gold[view.table];
  const size = view.pageSize ?? PAGE_SIZE;
  const { start, end } = pageWindow(rows.length, page, size);
  const card = view.table === 'mart_product_card' ? rows[0] : null;
  return (
    <section className="gold-card" aria-labelledby={`gold-${view.table}`}>
      <h3 id={`gold-${view.table}`}>
        {view.title} <small className="code">{view.table}</small>
      </h3>
      <p className="chart-section__note">{view.note}</p>
      {card && typeof card.light === 'string' && (
        <p className="gold-card__signal">
          <strong>{signalFor(card.light).label}.</strong> {signalFor(card.light).line}
        </p>
      )}
      <div className="table-card table-card--figures table-card--gold table-card--paged">
        <table>
          <caption className="visually-hidden">{view.title} for {product.name}</caption>
          <thead>
            <tr>{view.columns.map((c) => <th key={c.key} scope="col">{c.label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.slice(start, end).map((row, i) => (
              <tr key={i}>
                {view.columns.map((c, j) => (
                  <td key={c.key} data-label={c.label}>{j === 0 ? <strong><Clip>{goldCell(row[c.key], c.as)}</Clip></strong> : <Clip>{goldCell(row[c.key], c.as)}</Clip>}</td>
                ))}
              </tr>
            ))}
            <PadRows count={padCount(rows.length, end - start, size)} columns={view.columns.length} />
          </tbody>
        </table>
      </div>
      <Pager total={rows.length} page={page} onPage={setPage} noun="rows" size={size} />
    </section>
  );
}

function Done({ product, data }: { product: ShowcaseProduct; data: Showcase }) {
  return (
    <section className="chart-section" aria-labelledby="done-title">
      <h2 id="done-title">What was removed or replaced before showing it</h2>
      <p className="chart-section__note">
        The real counts for this product. Volunteers appear as {data.standIns.slice(0, 3).join(', ')} and so on; some of those are app accounts, shown the same way as people. Where something is hidden, the page says so and shows the gap.
      </p>
      <ul className="done-list">
        {doneRows(product).map((row) => (
          <li key={row.text}>
            <strong>{formatCount(row.count)}</strong> {row.text}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Journey({ data }: { data: Showcase }) {
  const [key, setKey] = useChoice<string>('product', KEYS);
  const product = data.products.find((p) => p.key === key) ?? data.products[0];
  return (
    <>
      <Switcher products={data.products} value={product.key} onChange={setKey} />
      <Flow product={product} />
      <SameField product={product} />
      {/* A new product starts every list from its first page: the key remounts the three lists. */}
      <Layer
        key={`raw-${product.key}`} id="raw" title="Step 1: the raw copy" noun="fields" withFilter={false} hiddenWord={data.markers.images}
        intro="Every field of this product's record as it arrived, in file order. Long values open when you press them. Images are replaced by a marker."
        rows={rawRows(product, data.markers)}
      />
      <Layer
        key={`silver-${product.key}`} id="silver" title="Step 2: the cleaned row" noun="columns" withFilter hiddenWord={data.markers.hidden}
        intro="The same product as one row of columns, turned on its side. Columns that stay on the private side are listed and marked rather than left out."
        rows={silverRows(product, data.markers)}
      />
      <section className="chart-section" aria-labelledby="gold-title">
        <h2 id="gold-title">Step 3: the tables for answers</h2>
        <p className="chart-section__note">The tables this site is drawn from, for this product. Each shows the readable columns; the full tables are wider.</p>
        <div className="gold-stack">
          {GOLD_VIEWS.map((view) => (
            <GoldTableCard key={`${product.key}-${view.table}`} view={view} product={product} />
          ))}
        </div>
      </section>
      <Done product={product} data={data} />
    </>
  );
}

export function HowItWorksPage() {
  const loaded = useResource(showcase);
  const { intro, sections } = pageSections('how-we-work');
  return (
    <div className="data-page">
      <PageTitle slug="how-we-work" />
      <div className="prose" dangerouslySetInnerHTML={{ __html: intro }} />
      {loaded.phase === 'ready' ? <Journey data={loaded.data} /> : <LoadState loaded={[loaded]} />}
      <Panels>
        {sections.map((section, i) => (
          <TextPanel key={section.title} id={`how-panel-${i}`} title={section.title} html={section.html} />
        ))}
      </Panels>
    </div>
  );
}
