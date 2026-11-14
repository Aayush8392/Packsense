import type { gsap as GsapType } from 'gsap';
import { BEATS } from './timeline';
import { countAt, scrambleMix } from './text';
import type { StoryData } from './storyData';

type Gsap = typeof GsapType;

/** The four things that take turns on the stage. Each slides in from one side and out the other, so no two are ever in the same place. */
export const GROUPS = ['file', 'main', 'result', 'page'] as const;

/**
 * How far off to the side a group waits, in percent of its own width, and the distance between two groups that pass each other: a little more
 * than one whole width, so they are never in the same place and the stage is never empty between them.
 */
export const OFF = 130;

/**
 * The whole story as one paused GSAP timeline whose duration is 100 units, so a position is "percent of the scroll". The scroll drives it with
 * ScrollTrigger (see StoryScroll.tsx); a test can scrub it with `.progress()` and read the picture back. The root holds the markup of World.tsx.
 */
export function buildStoryTimeline(root: HTMLElement, gsap: Gsap, data: StoryData): gsap.core.Timeline {
  const one = (name: string) => root.querySelector<HTMLElement>(`[data-el="${name}"]`) as HTMLElement;
  const all = (name: string) => Array.from(root.querySelectorAll<HTMLElement>(`[data-el="${name}"]`));
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power2.inOut' } });

  const file = one('file');
  const main = one('main');
  const table = one('table');
  const result = one('result');
  const page = one('page');
  const rows = all('row');
  const kept = rows.filter((row) => row.dataset.kind === 'kept');
  const dropped = rows.filter((row) => row.dataset.kind === 'dropped');
  const cards = all('card');
  const bars = all('bar');
  const captions = all('caption');
  const countEl = one('count');
  const labelEl = one('countLabel');
  const tableCount = one('tableCount');

  // The first picture: only the file is in view; everything else waits at the side.
  gsap.set([main, result, page], { xPercent: OFF });
  gsap.set(file, { xPercent: 0, y: 24, scale: 0.8, opacity: 1 });
  gsap.set(rows, { opacity: 0, x: -18 });
  gsap.set(one('titleB'), { opacity: 0, y: 8 });
  gsap.set(one('chip'), { opacity: 0 });
  gsap.set(cards, { opacity: 0 });
  gsap.set(one('more'), { opacity: 0 });
  gsap.set(bars, { scaleY: 0, transformOrigin: '50% 100%' });
  gsap.set(table, { '--hl': 0 });
  countEl.textContent = '0';
  labelEl.textContent = 'fields';
  tableCount.textContent = '0';
  ['flagN', 'nutN', 'changeN'].forEach((name) => (one(name).textContent = '0'));
  rows.forEach((row, i) => {
    const pair = data.pairs[i];
    const extra = data.dropped[i - data.pairs.length];
    row.querySelector('dt')!.textContent = pair ? pair.fromKey : (extra?.key ?? '');
    row.querySelector('dd')!.textContent = pair ? pair.fromValue : (extra?.value ?? '');
  });

  // 0 to 16: the file rises into view and settles.
  tl.to(file, { y: 0, scale: 1, duration: 10, ease: 'power2.out' }, 0);

  // 16 to 30: the file leaves to the left while the raw table arrives from the right.
  tl.to(file, { xPercent: -OFF * 2.6, duration: 12, ease: 'power3.inOut' }, 16);
  tl.to(main, { xPercent: 0, duration: 12, ease: 'power3.inOut' }, 16);

  // 28 to 40: the rows stream in one by one and the number of fields ticks up to the real count.
  tl.to(rows, { opacity: 1, x: 0, duration: 2.4, stagger: 0.9, ease: 'power2.out' }, 28);
  const fields = { n: 0 };
  tl.to(fields, { n: data.rawFields, duration: 10, ease: 'none', onUpdate: () => (countEl.textContent = String(Math.round(fields.n))) }, 28);
  tl.to(table, { '--hl': 1, duration: 3, ease: 'power1.inOut' }, 37);

  // 40 to 64: the same table is cleaned in place. The title changes, the names and values scramble into their cleaned form,
  // the fields that are not kept slide out and the table closes up, and the count ticks down to the columns that are kept.
  tl.to(one('titleA'), { opacity: 0, y: -8, duration: 3 }, 41);
  tl.to(one('titleB'), { opacity: 1, y: 0, duration: 3 }, 42);
  kept.forEach((row, i) => {
    const pair = data.pairs[i];
    if (!pair) return;
    const mix = { t: 0 };
    const key = row.querySelector('dt')!;
    const value = row.querySelector('dd')!;
    tl.to(
      mix,
      {
        t: 1,
        duration: 7,
        ease: 'none',
        onUpdate: () => {
          key.textContent = scrambleMix(pair.fromKey, pair.toKey, mix.t);
          value.textContent = scrambleMix(pair.fromValue, pair.toValue, mix.t);
        },
      },
      43 + i * 1.5,
    );
  });
  tl.to(table, { '--hl': 0, duration: 3, ease: 'power1.inOut' }, 49);
  tl.to(dropped, { xPercent: -130, opacity: 0, duration: 3, stagger: 1.6, ease: 'power2.in' }, 50);
  tl.to(dropped, { height: 0, paddingTop: 0, paddingBottom: 0, duration: 2, stagger: 1.6 }, 52);
  const columns = { n: data.rawFields };
  tl.to(
    columns,
    {
      n: data.silverColumns,
      duration: 10,
      ease: 'none',
      onUpdate: () => {
        countEl.textContent = String(Math.round(columns.n));
        labelEl.textContent = columns.n === data.rawFields ? 'fields' : 'columns kept';
      },
    },
    50,
  );

  // 64 to 80: the table closes into one record and eight tables burst out of it, with the count of tables ticking up.
  tl.to(root.querySelectorAll('.st-fade'), { opacity: 0, duration: 3 }, 64);
  tl.to(table, { scale: 0.2, duration: 6, ease: 'power3.inOut' }, 65);
  tl.to(one('chip'), { opacity: 1, duration: 2 }, 69);
  tl.to(table, { opacity: 0, duration: 2 }, 69.5);
  tl.fromTo(
    cards,
    {
      opacity: 0,
      scale: 0.2,
      x: (_index: number, card: HTMLElement) => fromCentre(card, 'x'),
      y: (_index: number, card: HTMLElement) => fromCentre(card, 'y'),
    },
    { opacity: 1, scale: 1, x: 0, y: 0, duration: 6, stagger: 1.2, ease: 'power3.out' },
    68,
  );
  tl.to(one('chip'), { opacity: 0, duration: 2 }, 73);
  tl.to(one('more'), { opacity: 1, duration: 2 }, 76);
  const tables = { n: 0 };
  tl.to(tables, { n: data.tableCount, duration: 7, ease: 'none', onUpdate: () => (tableCount.textContent = String(Math.round(tables.n))) }, 70);

  // 78 to 87: the tables slide out to the left and the chart and the product card slide in from the right, side by side like a conveyor; then the bars grow.
  conveyor(tl, main, result, 78, 9);
  tl.to(bars, { scaleY: 1, duration: 2, stagger: 0.3, ease: 'power2.out' }, 88);
  (
    [
      ['flagN', data.flagRows],
      ['nutN', data.nutritionRows],
      ['changeN', data.changeRows],
    ] as const
  ).forEach(([name, target], i) => {
    const counter = { n: 0 };
    tl.to(counter, { n: target, duration: 3.5, ease: 'none', onUpdate: () => (one(name).textContent = String(countAt(0, target, counter.n / (target || 1)))) }, 88 + i * 0.3);
  });

  // 93 to 100: the chart slides out to the left and a mock of the page slides in and stays.
  conveyor(tl, result, page, 93, 7);

  // The captions take turns in one place.
  captions.forEach((caption, i) => {
    const { from, to } = BEATS[i];
    gsap.set(caption, { opacity: i === 0 ? 1 : 0 });
    if (i > 0) tl.fromTo(caption, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 3, ease: 'power1.out' }, from);
    if (i < captions.length - 1) tl.to(caption, { opacity: 0, y: -14, duration: 3, ease: 'power1.in' }, to - 3);
  });

  tl.set({}, {}, 100); // the timeline is exactly 100 units long
  return tl;
}

/** Two groups on one belt: the first slides out to the left while the second slides in from the right, with the same timing, so the gap between them never changes. */
function conveyor(tl: gsap.core.Timeline, out: HTMLElement, into: HTMLElement, at: number, duration: number): void {
  tl.to(out, { xPercent: -OFF, duration, ease: 'power3.inOut' }, at);
  tl.fromTo(into, { xPercent: OFF }, { xPercent: 0, duration, ease: 'power3.inOut', immediateRender: false }, at);
}

/**
 * How far a card has to start from its place so that it starts at the middle of the box of cards, where the one-record chip is. It uses the
 * card's layout position, which the card's own movement does not change, so it gives the same answer at any point of the scroll.
 */
function fromCentre(card: HTMLElement, axis: 'x' | 'y'): number {
  const box = card.parentElement;
  if (!box) return 0;
  return axis === 'x' ? box.offsetWidth / 2 - (card.offsetLeft + card.offsetWidth / 2) : box.offsetHeight / 2 - (card.offsetTop + card.offsetHeight / 2);
}
