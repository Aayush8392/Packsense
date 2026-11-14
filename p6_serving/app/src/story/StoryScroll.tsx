import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { useResource } from '../data/resource';
import { showcase } from '../data/showcase';
import { formatCount } from '../format';
import { captions } from './beats';
import { storyFrom, type StoryData } from './storyData';
import { BEATS } from './timeline';
import { useStoryProgress } from './useStoryProgress';
import './story.css';

/** Whether the visitor asked for less motion. */
export function usePrefersReducedMotion(): boolean {
  const query = typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  const [reduced, setReduced] = useState(query?.matches ?? false);
  useEffect(() => {
    if (!query) return;
    const change = () => setReduced(query.matches);
    query.addEventListener?.('change', change);
    return () => query.removeEventListener?.('change', change);
  }, [query]);
  return reduced;
}

/** Loads the showcase file (a few hundred kilobytes) and hands the story's figures up. It is only drawn when the story is close, so the top of the home page never waits for it. */
function StoryLoader({ onData }: { onData: (data: StoryData | null) => void }) {
  const loaded = useResource(showcase);
  useEffect(() => {
    if (loaded.phase === 'ready') onData(storyFrom(loaded.data));
  }, [loaded, onData]);
  return null;
}

const money = (n: number) => formatCount(n);

function World({ data }: { data: StoryData | null }) {
  const hidden = 'hidden on purpose';
  return (
    <div className="story__world" aria-hidden="true">
      <div className="story-el story-file">
        <span className="story-file__doc" />
        <span className="story-file__label">Open Food Facts, today&rsquo;s file</span>
      </div>

      <div className="story-el story-plane story-raw">
        <p className="story-plane__head">Raw copy <small>bronze</small></p>
        <dl>
          {(data?.rawRows ?? []).map((row) => (
            <div key={row.key} className={`story-row${row.key === data?.userField ? ' story-row--user' : ''}`}>
              <dt>{row.key}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
        <p className="story-plane__foot">{data ? `… ${money(data.rawFields)} fields in all` : '…'}</p>
      </div>

      <div className="story-el story-plane story-clean">
        <p className="story-plane__head">Cleaned copy <small>silver</small></p>
        <dl>
          {(data?.cleanRows ?? []).map((row) =>
            row.key === data?.hiddenField ? (
              <div key={row.key} className="story-row story-row--swap">
                <dt>
                  <span className="story-from">{data.userField}</span>
                  <span className="story-to">{row.key}</span>
                </dt>
                <dd>
                  <span className="story-from">{data.userValue}</span>
                  <span className="story-to story-pill">{hidden}</span>
                </dd>
              </div>
            ) : (
              <div key={row.key} className="story-row">
                <dt>{row.key}</dt>
                <dd>{row.value}</dd>
              </div>
            ),
          )}
          {(data?.droppedKeys ?? []).map((key, i) => (
            <div key={key} className="story-row story-row--dropped" style={{ '--n': i } as CSSProperties}>
              <dt>{key}</dt>
              <dd />
            </div>
          ))}
        </dl>
        <p className="story-count">
          <span className="story-count__swap">
            <span className="story-from">{data ? money(data.rawFields) : ''}</span>
            <span className="story-to">{data ? money(data.silverColumns) : ''}</span>
          </span>{' '}
          {data ? 'columns kept' : ''}
        </p>
      </div>

      <div className="story-el story-tables">
        <p className="story-chip">1 record</p>
        {(data?.tables ?? []).map((table, i) => (
          <div key={table.name} className="story-card" style={{ '--i': i } as CSSProperties}>
            <p>{table.name}</p>
            <span />
            <span />
            <small>{table.rows} {table.rows === 1 ? 'row' : 'rows'}</small>
          </div>
        ))}
        {data && data.tableCount > data.tables.length && <p className="story-more">+ {data.tableCount - data.tables.length} more tables</p>}
      </div>

      <div className="story-el story-result">
        <div className="story-chart">
          <p>Flags per day</p>
          <div>
            {[30, 44, 38, 62, 52, 78].map((h, i) => (
              <span key={i} style={{ '--h': `${h}%`, '--k': i } as CSSProperties} />
            ))}
          </div>
        </div>
        <div className="story-product">
          <p className="story-product__name">{data?.name ?? ''}</p>
          <p>{data?.code ?? ''}</p>
          <p>{data ? `${data.flagRows} flags` : ''}</p>
          <p>{data ? `${data.nutritionRows} nutrition sets` : ''}</p>
          <p>{data ? `${data.changeRows} days of edits` : ''}</p>
        </div>
      </div>

      <div className="story-el story-page">
        <p className="story-page__search">Look up a barcode</p>
        <div>
          <span>Brands</span>
          <span>Data quality</span>
          <span>Daily changes</span>
          <span>Download</span>
        </div>
      </div>
    </div>
  );
}

/** The scroll story: a tall section with a stage that stays on screen while the scroll drives the scene (see scene.ts). */
function StoryStage({ data }: { data: StoryData | null }) {
  const section = useRef<HTMLElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const [beat, setBeat] = useState(0);
  const [scrub, setScrub] = useState<number | null>(null);
  useStoryProgress(section, stage, setBeat, scrub);
  const words = captions(data);

  return (
    <>
      <section className="story" ref={section} aria-labelledby="story-title">
        <a className="skip-link story__skip" href="#after-story">Skip the animation</a>
        <div className="story__stage" ref={stage}>
          <h2 id="story-title" className="story__title">How it works, in one scroll</h2>
          <World data={data} />
          <ol className="story__captions">
            {words.map((word, i) => (
              <li key={word.title} aria-current={beat === i ? 'step' : undefined}>
                <strong>{word.title}</strong>
                <span>{word.text}</span>
              </li>
            ))}
          </ol>
          <ol className="story__dots" aria-hidden="true">
            {BEATS.map((b, i) => (
              <li key={b.id} data-on={beat === i}></li>
            ))}
          </ol>
          {import.meta.env.DEV && (
            <label className="story__scrub">
              Scrub (development only)
              <input type="range" min={0} max={1000} value={scrub === null ? 0 : Math.round(scrub * 1000)} onChange={(e) => setScrub(Number(e.target.value) / 1000)} />
              <button type="button" onClick={() => setScrub(null)}>Follow the scroll</button>
            </label>
          )}
        </div>
      </section>
      <div id="after-story" tabIndex={-1} />
    </>
  );
}

/** For a visitor who asked for less motion: the five stages as a plain list, with no scene and no tall section. */
function StoryStill({ data }: { data: StoryData | null }) {
  return (
    <section className="story-still" aria-labelledby="story-title">
      <h2 id="story-title">How it works, in five steps</h2>
      <ol>
        {captions(data).map((word) => (
          <li key={word.title}>
            <strong>{word.title}</strong> {word.text}
          </li>
        ))}
      </ol>
    </section>
  );
}

export function StoryScroll() {
  const reduced = usePrefersReducedMotion();
  const [data, setData] = useState<StoryData | null>(null);
  const [near, setNear] = useState(false);
  const marker = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = marker.current;
    if (!el || typeof IntersectionObserver === 'undefined') {
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin: '1500px 0px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <>
      <div ref={marker} className="story__marker" aria-hidden="true" />
      {near && <StoryLoader onData={setData} />}
      {reduced ? <StoryStill data={data} /> : <StoryStage data={data} />}
    </>
  );
}
