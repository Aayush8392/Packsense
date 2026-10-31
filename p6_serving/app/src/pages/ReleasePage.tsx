import { useId, useState } from 'react';
import { Clip, PadRows, Pager, padCount, pageWindow } from '../charts/Pager';
import { LoadState, PageTitle, Panels, TextPanel, pageSections } from '../components/pageParts';
import { COLUMN_GUIDE, SAMPLE_COLUMNS } from '../data/columnGuide';
import { RELEASE_FILE_URL, RELEASE_REPO, release, releaseSchedule, versionRows, type Release } from '../data/release';
import { useResource } from '../data/resource';
import { formatCount, formatDay } from '../format';

const dayOf = (iso: string) => formatDay(iso.slice(0, 10));

/** The credit line a user can paste next to their own work. It names Open Food Facts and the licence, as the licence asks. */
export function creditLine(data: Release): string {
  return `Contains data from Open Food Facts (https://openfoodfacts.org), available under the Open Database License (https://opendatacommons.org/licenses/odbl/1-0/). Prepared by PackSense, India product catalogue, release ${data.version} (${RELEASE_REPO}).`;
}

/** Saves the file with a real download. A plain link would only show the text in the browser, because the file lives on another site. */
export async function saveFile(url: string, name: string): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`The file could not be fetched (${response.status})`);
  const blob = await response.blob();
  const href = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement('a');
    anchor.href = href;
    anchor.download = name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(href), 10_000);
  }
}

function DownloadButton({ version }: { version: string }) {
  const [state, setState] = useState<'idle' | 'working' | 'done' | 'failed'>('idle');
  const start = async () => {
    setState('working');
    try {
      await saveFile(RELEASE_FILE_URL, `india_products_${version}.csv`);
      setState('done');
    } catch {
      setState('failed');
    }
  };
  return (
    <>
      <button type="button" className="button button--primary" onClick={start} disabled={state === 'working'}>
        {state === 'working' ? 'Downloading…' : 'Download the CSV file'}
      </button>
      <span role="status" className="release-card__status">
        {state === 'done' && 'The file was saved to your downloads.'}
        {state === 'failed' && (
          <>
            The download could not start here. <a href={RELEASE_FILE_URL}>Open the file in the browser</a> and save it from there.
          </>
        )}
      </span>
    </>
  );
}

function DownloadCard({ data }: { data: Release }) {
  return (
    <section className="chart-section release-card" aria-labelledby="release-download">
      <h2 id="release-download">India product catalogue, release {data.version}</h2>
      <dl className="release-card__facts">
        <div><dt>Products</dt><dd>{formatCount(data.products)}</dd></div>
        <div><dt>Built</dt><dd>{dayOf(data.builtAt)}</dd></div>
        <div><dt>Open Food Facts copy of</dt><dd>{data.sourceDumpDate ? formatDay(data.sourceDumpDate) : '—'}</dd></div>
      </dl>
      <p className="release-card__actions">
        <DownloadButton version={data.version} />
        <a className="button button--quiet" href={RELEASE_REPO}>Data card and all releases on Hugging Face</a>
      </p>
      <p className="chart-section__note">The file is a plain CSV. It opens in any spreadsheet or data tool; read the steps below first so barcodes stay intact.</p>
    </section>
  );
}

function SampleTable({ data }: { data: Release }) {
  return (
    <section className="chart-section" aria-labelledby="release-sample">
      <h2 id="release-sample">What is inside the table</h2>
      <p className="chart-section__note">
        The first {data.sample.rows.length} rows of the file, as it writes them (the file is sorted by barcode, so the first rows are the oldest codes). A dash means the cell is empty: we have no value.
      </p>
      <div className="table-card table-card--figures table-card--paged">
        <table>
          <caption className="visually-hidden">The first rows of the India file</caption>
          <thead>
            <tr>{SAMPLE_COLUMNS.map((c) => <th key={c.key} scope="col">{c.label}</th>)}</tr>
          </thead>
          <tbody>
            {data.sample.rows.map((row, i) => (
              <tr key={i}>
                {SAMPLE_COLUMNS.map((c, j) => {
                  const value = row[c.key] ?? '';
                  const text = value === '' ? '—' : value;
                  return <td key={c.key} data-label={c.label}>{j === 0 ? <strong>{text}</strong> : <Clip>{text}</Clip>}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ColumnGuide({ data }: { data: Release }) {
  const [page, setPage] = useState(0);
  const fills = data.fill.length > 0 ? data.fill : data.sample.columns.map((column) => ({ column, rows: NaN, share: NaN }));
  const { start, end } = pageWindow(fills.length, page);
  const share = (value: number) => (Number.isNaN(value) ? '—' : `${(value * 100).toFixed(1)}%`);
  return (
    <section className="chart-section" aria-labelledby="release-columns">
      <h2 id="release-columns">The {fills.length} columns, in plain words</h2>
      <p className="chart-section__note">What each column holds, and the share of the {formatCount(data.products)} products that have a value in it.</p>
      <div className="table-card table-card--figures table-card--paged">
        <table>
          <caption className="visually-hidden">The columns of the India file</caption>
          <thead>
            <tr><th scope="col">Column</th><th scope="col">What it holds</th><th scope="col">Filled</th></tr>
          </thead>
          <tbody>
            {fills.slice(start, end).map((fill) => (
              <tr key={fill.column}>
                <td data-label="Column"><strong><code>{fill.column}</code></strong></td>
                <td data-label="What it holds"><Clip>{COLUMN_GUIDE[fill.column] ?? '—'}</Clip></td>
                <td data-label="Filled">{share(fill.share)}</td>
              </tr>
            ))}
            <PadRows count={padCount(fills.length, end - start)} columns={3} />
          </tbody>
        </table>
      </div>
      <Pager total={fills.length} page={page} onPage={setPage} noun="columns" />
    </section>
  );
}

function CreditLine({ data }: { data: Release }) {
  const id = useId();
  const [copied, setCopied] = useState<'no' | 'yes' | 'failed'>('no');
  const text = creditLine(data);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied('yes');
    } catch {
      setCopied('failed');
      (document.getElementById(id) as HTMLTextAreaElement | null)?.select();
    }
  };
  return (
    <section className="chart-section" aria-labelledby="release-credit">
      <h2 id="release-credit">Credit line, ready to copy</h2>
      <p className="chart-section__note">Put this next to anything you build from the file. The licence asks for it.</p>
      <label htmlFor={id} className="visually-hidden">Credit line</label>
      <textarea id={id} className="release-credit" readOnly rows={4} value={text} />
      <p className="release-credit__actions">
        <button type="button" className="button button--quiet" onClick={copy}>Copy the credit line</button>
        <span role="status" className="release-credit__status">
          {copied === 'yes' ? 'Copied.' : copied === 'failed' ? 'Copying is not allowed here. The text is selected: press Ctrl+C.' : ''}
        </span>
      </p>
    </section>
  );
}

function OpeningSteps() {
  return (
    <section className="chart-section" aria-labelledby="release-open">
      <h2 id="release-open">How to open the file without breaking barcodes</h2>
      <p className="chart-section__note">
        A spreadsheet that opens the file by double-click reads each barcode as a number. It drops leading zeros and turns long codes into a form like 8.9E+12, and that cannot be undone. Bring the file in through the import dialog instead.
      </p>
      <div className="steps">
        <div>
          <h3>In Excel</h3>
          <ol>
            <li>Open Excel with an empty sheet. Do not double-click the file.</li>
            <li>Choose Data, then From Text/CSV, and pick the file.</li>
            <li>Set File Origin to “65001: Unicode (UTF-8)”.</li>
            <li>Press Transform Data. Select the “code” column and set its Data Type to Text.</li>
            <li>Press Close &amp; Load.</li>
          </ol>
        </div>
        <div>
          <h3>In Google Sheets</h3>
          <ol>
            <li>Choose File, then Import, then Upload, and pick the file.</li>
            <li>Set “Convert text to numbers, dates and formulas” to No.</li>
            <li>Press Import data.</li>
          </ol>
        </div>
        <div>
          <h3>In code</h3>
          <p>Read the “code” column as text. In Python with pandas that is <code>{"dtype={'code': str}"}</code>.</p>
        </div>
      </div>
    </section>
  );
}

function Versions({ data }: { data: Release }) {
  const rows = versionRows(data);
  return (
    <section className="chart-section" aria-labelledby="release-versions">
      <h2 id="release-versions">Versions and the monthly schedule</h2>
      <p className="chart-section__note">
        A new release is built once a month{releaseSchedule() ? ` (${releaseSchedule()})` : ''}. Each one is a new file, and the change list says what was added, removed or changed since the last.
      </p>
      <div className="table-card table-card--figures">
        <table>
          <caption className="visually-hidden">Releases of the India file</caption>
          <thead>
            <tr><th scope="col">Release</th><th scope="col">Built</th><th scope="col">Products</th><th scope="col">Status</th><th scope="col">What changed</th></tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.version}>
                <td data-label="Release"><strong>{row.version}</strong></td>
                <td data-label="Built">{dayOf(row.builtAt)}</td>
                <td data-label="Products">{row.products === null ? '—' : formatCount(row.products)}</td>
                <td data-label="Status">{row.status}</td>
                <td data-label="What changed">{row.summary || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function NotPublished() {
  return (
    <section className="chart-section release-state" aria-labelledby="release-none">
      <h2 id="release-none">The first release has not been published yet</h2>
      <p>The file appears here as soon as it is built. It will also be on the Hugging Face page below.</p>
      <p><a className="button button--quiet" href={RELEASE_REPO}>Data card and all releases on Hugging Face</a></p>
    </section>
  );
}

function Unreadable() {
  return (
    <section className="chart-section release-state" aria-labelledby="release-error">
      <h2 id="release-error">The release details could not be loaded just now</h2>
      <p>The file itself is still available from the Hugging Face page.</p>
      <p className="release-card__actions">
        <button type="button" className="button button--primary" onClick={() => { release.reset(); release.start(); }}>Try again</button>
        <a className="button button--quiet" href={RELEASE_REPO}>Data card and all releases on Hugging Face</a>
      </p>
    </section>
  );
}

export function ReleasePage() {
  const loaded = useResource(release);
  const { intro, sections } = pageSections('india-release');
  return (
    <div className="data-page">
      <PageTitle slug="india-release" />
      <div className="prose" dangerouslySetInnerHTML={{ __html: intro }} />
      {loaded.phase === 'ready' && loaded.data.published && (
        <>
          <DownloadCard data={loaded.data.release} />
          <SampleTable data={loaded.data.release} />
          <ColumnGuide data={loaded.data.release} />
        </>
      )}
      {loaded.phase === 'ready' && !loaded.data.published && <NotPublished />}
      {loaded.phase === 'error' && <Unreadable />}
      {(loaded.phase === 'idle' || loaded.phase === 'loading') && <LoadState loaded={[loaded]} />}
      <Panels>
        {sections.map((section, i) => (
          <TextPanel key={section.title} id={`release-panel-${i}`} title={section.title} html={section.html} />
        ))}
      </Panels>
      {loaded.phase === 'ready' && loaded.data.published && (
        <>
          <CreditLine data={loaded.data.release} />
        </>
      )}
      <OpeningSteps />
      {loaded.phase === 'ready' && loaded.data.published && <Versions data={loaded.data.release} />}
    </div>
  );
}
