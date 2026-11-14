import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { useResource } from '../data/resource';
import { showcase } from '../data/showcase';
import { captions } from './beats';
import type { StoryData } from './storyData';
import { storyFrom } from './storyData';
import { BEATS, TOTAL, beatAt } from './timeline';
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
function StoryLoader({ onData, onFail }: { onData: (data: StoryData) => void; onFail: () => void }) {
  const loaded = useResource(showcase);
  useEffect(() => {
    if (loaded.phase === 'ready') {
      const data = storyFrom(loaded.data);
      if (data) onData(data);
      else onFail();
    } else if (loaded.phase === 'error') onFail();
  }, [loaded, onData, onFail]);
  return null;
}

/** The scene: four things that take turns on the stage (the file, the table that is cleaned and split, the chart and the product card, a mock of the page). Their text is filled in by the timeline. */
export function World({ data }: { data: StoryData | null }) {
  const rows = data ? [...data.pairs.map((pair) => ({ kind: 'kept', user: pair.user })), ...data.dropped.map(() => ({ kind: 'dropped', user: false }))] : [];
  return (
    <div className="story__world" aria-hidden="true">
      <div className="st-lane st-file" data-group="file" data-el="file">
        <span className="st-file__doc" />
        <span className="st-file__label">Open Food Facts, today&rsquo;s file</span>
      </div>

      <div className="st-lane st-main" data-group="main" data-el="main">
        <div className="st-table" data-el="table">
          <p className="st-head st-fade">
            <span data-el="titleA">Raw copy <small>bronze</small></span>
            <span data-el="titleB">Cleaned copy <small>silver</small></span>
          </p>
          <p className="st-count st-fade">
            <b data-el="count" /> <span data-el="countLabel" />
          </p>
          <dl className="st-rows st-fade">
            {rows.map((row, i) => (
              <div key={i} className={`st-row${row.user ? ' st-row--user' : ''}`} data-el="row" data-kind={row.kind}>
                <dt />
                <dd />
              </div>
            ))}
          </dl>
        </div>
        <div className="st-cards" data-el="cards">
          <p className="st-chip" data-el="chip">1 record</p>
          <svg className="st-links" aria-hidden="true" focusable="false">
            {(data?.tables ?? []).map((table) => (
              <line key={table.name} data-el="link" x1="50%" y1="50%" x2="50%" y2="50%" pathLength={1} />
            ))}
          </svg>
          {(data?.tables ?? []).map((table) => (
            <div key={table.name} className="st-card" data-el="card">
              <p>{table.name}</p>
              <span />
              <span />
              <small>{table.rows} {table.rows === 1 ? 'row' : 'rows'}</small>
            </div>
          ))}
          <p className="st-more" data-el="more"><b data-el="tableCount" /> tables in all</p>
        </div>
      </div>

      <div className="st-lane st-flags" data-group="flags" data-el="flags">
        <p className="st-flags__head">
          <b>{data?.history.name ?? ''}</b>
          <span>
            <b data-el="versionCount" /> versions, <b data-el="flagCount" /> flags
          </span>
        </p>
        <p className="st-flags__axis">
          <span>{data?.history.startLabel ?? ''}</span>
          <span>{data?.history.endLabel ?? ''}</span>
        </p>
        <ul className="st-flagrows">
          {(data?.history.bars ?? []).map((bar, i) => (
            <li key={i} data-el="flagRow" data-severity={bar.severity}>
              <span className="st-flagrows__label">{bar.label}</span>
              <span className="st-flagrows__track">
                <i data-el="flagBar" style={{ '--from': `${(bar.from * 100).toFixed(1)}%`, '--to': `${(bar.to * 100).toFixed(1)}%` } as CSSProperties} />
                {bar.ended && <em data-el="flagEnd" style={{ '--to': `${(bar.to * 100).toFixed(1)}%` } as CSSProperties} />}
              </span>
            </li>
          ))}
        </ul>
        <p className="st-flags__key">A flag that ended is marked with a ring.</p>
      </div>

      <div className="st-lane st-checks" data-group="checks" data-el="checks">
        <p className="st-checks__head">
          <b>{data?.checks.name ?? ''}</b>
          <span>
            <b data-el="checkOk" /> agree, <b data-el="checkBad" /> do not
          </span>
        </p>
        <ul className="st-checkrows">
          {(data?.checks.rows ?? []).map((row, i) => (
            <li key={i} data-el="checkRow">
              <span>{row.label}</span>
              <i data-el="stamp" data-status={row.ok ? 'ok' : 'bad'}>{row.ok ? '\u2713' : '!'}</i>
            </li>
          ))}
        </ul>
      </div>

      <div className="st-lane st-result" data-group="result" data-el="result">
        <div className="st-chart">
          <p>Flags per day</p>
          <div>
            {[30, 44, 38, 62, 52, 78].map((h, i) => (
              <span key={i} data-el="bar" style={{ '--h': `${h}%` } as CSSProperties} />
            ))}
          </div>
        </div>
        <div className="st-product">
          <p className="st-product__name">{data?.name ?? ''}</p>
          <p>{data?.code ?? ''}</p>
          <p><b data-el="flagN" /> flags</p>
          <p><b data-el="nutN" /> nutrition sets</p>
          <p><b data-el="changeN" /> days of edits</p>
        </div>
      </div>

      <div className="st-lane st-page" data-group="page" data-el="page">
        <p className="st-page__label">Look up a barcode</p>
        <p className="st-page__search">
          <span className="st-page__icon">|||</span>
          <span data-el="typed" />
        </p>
        <div className="st-page__tiles">
          <span data-el="tile">Brands</span>
          <span data-el="tile">Data quality</span>
          <span data-el="tile">Daily changes</span>
          <span data-el="tile">Download</span>
        </div>
        <div className="st-lookup" data-el="lookupCard">
          <p className="st-lookup__name">{data?.name ?? ''}</p>
          <p>{data?.code ?? ''}</p>
          <p>{data ? `${data.flagRows} flags, ${data.nutritionRows} nutrition sets` : ''}</p>
        </div>
      </div>
    </div>
  );
}

export interface StoryStageProps {
  data: StoryData;
  /** Called with the timeline once it is built (the tests scrub it). */
  onReady?: (timeline: gsap.core.Timeline) => void;
}

/**
 * The scroll story: a tall section with a stage that stays on screen while the scroll drives one GSAP timeline (motion.ts). GSAP is loaded when the
 * stage is first drawn, so it is not part of the home page's first download.
 */
export function StoryStage({ data, onReady }: StoryStageProps) {
  const section = useRef<HTMLElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const timeline = useRef<{ tl: gsap.core.Timeline; trigger: ScrollTrigger } | null>(null);
  const [beat, setBeat] = useState(0);
  const [ready, setReady] = useState(false);
  const [scrub, setScrub] = useState<number | null>(null);
  const words = captions(data);
  const activeBeat = scrub === null ? beat : beatAt(scrub * TOTAL);

  useEffect(() => {
    let cancelled = false;
    let cleanup = () => undefined as void;
    (async () => {
      const [{ gsap }, { ScrollTrigger }, { buildStoryTimeline }] = await Promise.all([import('gsap'), import('gsap/ScrollTrigger'), import('./motion')]);
      const stageEl = stage.current;
      const sectionEl = section.current;
      if (cancelled || !stageEl || !sectionEl) return;
      gsap.registerPlugin(ScrollTrigger);
      const tl = buildStoryTimeline(stageEl, gsap, data);
      const headerHeight = () => parseFloat(getComputedStyle(stageEl).top) || 0;
      const trigger = ScrollTrigger.create({
        animation: tl,
        trigger: sectionEl,
        start: () => `top ${headerHeight()}px`,
        end: () => `bottom ${headerHeight() + stageEl.offsetHeight}px`,
        scrub: 1.2,
        invalidateOnRefresh: true,
        onUpdate: (self) => setBeat(beatAt(self.progress * TOTAL)),
      });
      timeline.current = { tl, trigger };
      setReady(true);
      onReady?.(tl);
      cleanup = () => {
        trigger.kill();
        tl.kill();
        timeline.current = null;
      };
    })();
    return () => {
      cancelled = true;
      cleanup();
    };
  }, [data, onReady]);

  // The development slider holds the story at one frame instead of following the scroll.
  useEffect(() => {
    const live = timeline.current;
    if (!live) return;
    if (scrub === null) live.trigger.enable();
    else {
      live.trigger.disable(false);
      live.tl.progress(scrub, false);
    }
  }, [scrub, ready]);

  return (
    <>
      <section className={`story${ready ? ' story--ready' : ''}`} ref={section} aria-labelledby="story-title">
        <a className="skip-link story__skip" href="#after-story">Skip the animation</a>
        <div className="story__stage" ref={stage}>
          <h2 id="story-title" className="story__title">How it works, in one scroll</h2>
          <World data={data} />
          <ol className="story__captions">
            {words.map((word, i) => (
              <li key={word.title} data-el="caption" aria-current={activeBeat === i ? 'step' : undefined}>
                <strong>{word.title}</strong>
                <span>{word.text}</span>
              </li>
            ))}
          </ol>
          <div className="story__progress" aria-hidden="true">
            <span data-el="progress" />
          </div>
          <ol className="story__dots" aria-hidden="true">
            {BEATS.map((b, i) => (
              <li key={b.id} data-on={activeBeat === i}></li>
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

/** For a visitor who asked for less motion, or when the figures could not be loaded: the five stages as a plain list, with no scene and no tall section. */
export function StoryStill({ data }: { data: StoryData | null }) {
  return (
    <section className="story-still" aria-labelledby="story-title">
      <h2 id="story-title">How it works, in seven steps</h2>
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
  const [failed, setFailed] = useState(false);
  const [near, setNear] = useState(false);
  const marker = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = marker.current;
    if (!el || typeof IntersectionObserver === 'undefined') {
      setNear(true);
      return;
    }
    // Two ways to notice that the story is close: the observer, and a check on scroll (a browser may hold observer callbacks back while a window is not drawn).
    const check = () => {
      if (el.getBoundingClientRect().top < window.innerHeight + 1500) {
        setNear(true);
        done();
      }
    };
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          done();
        }
      },
      { rootMargin: '1500px 0px' },
    );
    function done() {
      observer.disconnect();
      window.removeEventListener('scroll', check);
    }
    observer.observe(el);
    window.addEventListener('scroll', check, { passive: true });
    return done;
  }, []);

  return (
    <>
      <div ref={marker} className="story__marker" aria-hidden="true" />
      {near && !reduced && !data && !failed && <StoryLoader onData={setData} onFail={() => setFailed(true)} />}
      {reduced || failed ? <StoryStill data={data} /> : data ? <StoryStage data={data} /> : <div className="story__waiting" aria-hidden="true" />}
    </>
  );
}
