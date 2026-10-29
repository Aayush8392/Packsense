import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router';
import { pageBySlug } from '../content';
import { splitBlocks } from '../content/parse';
import { dailyJobsVerdict, editsOnDay, nextUpdateDue, rightNow } from '../data/derive';
import { useResource, type Loaded } from '../data/resource';
import { changeDaily, pipelineHealth, siteStatus } from '../data/siteData';
import { addDays, describeMoment, formatCount, formatDay, utcDay } from '../format';

/** Where each line of "What you can do on this site" leads, in the order the text lists them. */
const DO_LINKS: { to: string; where: string }[] = [
  { to: '/explore/brands', where: 'Brands' },
  { to: '/explore/quality', where: 'Data quality over time' },
  { to: '/explore/changes', where: 'Daily changes' },
  { to: '/get-the-data', where: 'Get the data' },
  { to: '/how-it-works', where: 'How PackSense works' },
];

function splitLabel(block: string, label: string): { heading: string; body: string } {
  const match = new RegExp(`<p><strong>(${label})\\.</strong>\\s*([\\s\\S]*)</p>`).exec(block);
  if (!match) throw new Error(`Home text has no paragraph that starts with '${label}.'`);
  return { heading: match[1], body: match[2] };
}

function BarcodeBox() {
  const navigate = useNavigate();
  const [value, setValue] = useState('');
  const [problem, setProblem] = useState('');

  function submit(event: FormEvent) {
    event.preventDefault();
    const digits = value.replace(/\s+/g, '');
    if (!/^\d{8,14}$/.test(digits)) {
      setProblem('Enter 8 to 14 digits, with no letters.');
      return;
    }
    setProblem('');
    navigate(`/look-up?barcode=${digits}`);
  }

  return (
    <div className="barcode-box">
      <form role="search" aria-label="Barcode" onSubmit={submit} noValidate>
        <label htmlFor="barcode-input">Look up a barcode</label>
        <div className="barcode-box__row">
          <div className="barcode-box__field">
            <span className="barcode-box__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="20" height="20" focusable="false">
                <path d="M4 5v14M7 5v14M11 5v14M14 5v14M17 5v14M20 5v14" fill="none" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            </span>
            <input
              id="barcode-input"
              type="text"
              inputMode="numeric"
              autoComplete="off"
              placeholder="8 to 14 digits"
              value={value}
              aria-describedby="barcode-problem"
              aria-invalid={problem ? true : undefined}
              onChange={(event) => setValue(event.target.value)}
            />
          </div>
          <button type="submit" className="button button--primary">Look up</button>
        </div>
        <p id="barcode-problem" className="form-problem" role="alert">{problem}</p>
      </form>
    </div>
  );
}

type Settled = 'loading' | 'error' | 'ready';

/** One state for several files: any failure is a failure, anything still on its way is loading. */
function settle(...loaded: Loaded<unknown>[]): Settled {
  if (loaded.some((l) => l.phase === 'error')) return 'error';
  return loaded.every((l) => l.phase === 'ready') ? 'ready' : 'loading';
}

/** A figure that is loading, could not load, or is known. While it is not known it shows a dash and says why to a screen reader. */
function Figure({ state, children }: { state: Settled; children: ReactNode }) {
  if (state === 'ready') return <>{children}</>;
  return (
    <>
      <span aria-hidden="true">—</span>
      <span className="visually-hidden">{state === 'loading' ? 'loading' : 'could not be loaded'}</span>
    </>
  );
}

/** Home, laid out like the Stitch design: hero, barcode box, three numbers, "Right now", then what to do and what not to expect. */
export function Home({ now: given }: { now?: Date }) {
  const page = pageBySlug('home');
  const [now] = useState(() => given ?? new Date());
  const status = useResource(siteStatus);
  const changes = useResource(changeDaily);
  const health = useResource(pipelineHealth);

  useEffect(() => {
    document.title = 'PackSense — Packaged food data, checked every day';
  }, []);
  if (!page) throw new Error("No page text for 'home'");

  const blocks = splitBlocks(page.html);
  const firstH2 = blocks.findIndex((b) => b.startsWith('<h2>'));
  const lead = blocks.slice(0, firstH2).join('');
  const list = blocks.find((b) => b.startsWith('<ul>')) ?? '';
  const items = [...list.matchAll(/<li>([\s\S]*?)<\/li>/g)].map((m) => m[1]);
  if (items.length !== DO_LINKS.length) throw new Error(`Home lists ${items.length} things to do; the page expects ${DO_LINKS.length}`);
  const doHeading = (blocks[firstH2] ?? '').replace(/<\/?h2>/g, '');
  const notDo = splitLabel(blocks.find((b) => b.includes('<strong>What PackSense does not do.')) ?? '', 'What PackSense does not do');
  const small = splitLabel(blocks.find((b) => b.includes('<strong>Small print.')) ?? '', 'Small print');

  const statusData = status.phase === 'ready' ? status.data : null;
  const editsDay = statusData?.lastCompleteDay ?? '';
  const editsLabel = editsDay && editsDay !== addDays(utcDay(now), -1) ? `Edits seen on ${formatDay(editsDay)}` : 'Edits seen yesterday';
  const edits = statusData && changes.phase === 'ready' ? editsOnDay(changes.data, statusData.lastCompleteDay) : null;

  const moments = health.phase === 'ready' ? rightNow(health.data) : null;
  const verdict = health.phase === 'ready' ? dailyJobsVerdict(health.data) : null;
  const anyFailed = [status, changes, health].some((l) => l.phase === 'error');

  const numbers: { label: string; state: Settled; value: ReactNode }[] = [
    { label: 'Products we hold', state: settle(status), value: statusData ? formatCount(statusData.productsAll) : '' },
    { label: editsLabel, state: settle(status, changes), value: edits === null ? 'fewer than 5' : formatCount(edits) },
    { label: 'Products in the India slice', state: settle(status), value: statusData ? formatCount(statusData.productsIndia) : '' },
  ];

  const facts: { label: string; state: Settled; value: ReactNode }[] = [
    {
      label: "Open Food Facts' newest file arrived",
      state: settle(health),
      value: moments?.offFilePublished ? describeMoment(moments.offFilePublished, now) : 'not known yet',
    },
    {
      label: 'Our copy received it',
      state: settle(health),
      value: moments?.ourCopyReceived ? describeMoment(moments.ourCopyReceived, now) : 'not known yet',
    },
    {
      label: 'Daily jobs',
      state: settle(health),
      value: verdict ? (
        verdict.missing.length === 0 && verdict.failed.length === 0 ? (
          <span className="verdict verdict--ok"><span aria-hidden="true">✓ </span>Every daily job ran on {formatDay(verdict.day)}</span>
        ) : (
          <span className="verdict verdict--attention">
            <span aria-hidden="true">! </span>
            {verdict.missing.length + verdict.failed.length} of {verdict.expected} daily jobs did not run cleanly on {formatDay(verdict.day)}
          </span>
        )
      ) : (
        'not enough history to say'
      ),
    },
    {
      label: 'Newest complete day in the charts',
      state: settle(status),
      value: statusData ? formatDay(statusData.lastCompleteDay) : '',
    },
    { label: 'Next update due', state: 'ready', value: nextUpdateDue(now) },
  ];

  return (
    <div className="home">
      <section className="hero">
        <h1>{page.heading}</h1>
        <div className="hero__text" dangerouslySetInnerHTML={{ __html: lead }} />
      </section>

      <BarcodeBox />

      <section className="numbers" aria-label="Headline numbers" aria-busy={numbers.some((n) => n.state === 'loading')}>
        {numbers.map((number) => (
          <div className="stat-card" key={number.label}>
            <p className="stat-card__label">{number.label}</p>
            <p className="stat-card__value">
              <Figure state={number.state}>{number.value}</Figure>
            </p>
          </div>
        ))}
      </section>

      {anyFailed && (
        <p className="data-problem" role="status">
          Some figures could not be loaded just now. The rest of the page works; try again in a little while.
        </p>
      )}

      <section className="right-now" aria-labelledby="right-now-heading">
        <h2 id="right-now-heading">
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
            <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2" />
            <path d="M12 7v5l3 2" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          Right now
        </h2>
        <dl>
          {facts.map((fact) => (
            <div key={fact.label}>
              <dt>{fact.label}</dt>
              <dd>
                <Figure state={fact.state}>{fact.value}</Figure>
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <div className="home__lower">
        <section className="do-list" aria-labelledby="do-heading">
          <h2 id="do-heading" dangerouslySetInnerHTML={{ __html: doHeading }} />
          <ul>
            {items.map((item, i) => (
              <li key={DO_LINKS[i].to}>
                <Link to={DO_LINKS[i].to}>
                  <span className="do-list__text" dangerouslySetInnerHTML={{ __html: item }} />
                  <span className="do-list__where">{DO_LINKS[i].where}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <aside className="not-do" aria-labelledby="not-do-heading">
          <h2 id="not-do-heading">{notDo.heading}</h2>
          <p dangerouslySetInnerHTML={{ __html: notDo.body }} />
          <h3>{small.heading}</h3>
          <p className="not-do__small" dangerouslySetInnerHTML={{ __html: small.body }} />
        </aside>
      </div>
    </div>
  );
}
