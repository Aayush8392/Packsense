import type { gsap as GsapType } from 'gsap';
import { BEATS, TOTAL } from './timeline';
import { countAt, scrambleMix } from './text';
import type { StoryData } from './storyData';

type Gsap = typeof GsapType;

/** The things that take turns on the stage. Each slides in from one side and out the other, so no two are ever in the same place. */
export const GROUPS = ['file', 'main', 'flags', 'checks', 'result', 'page'] as const;

/**
 * How far off to the side a group waits, in percent of its own width, and the distance between two groups that pass each other: a little more
 * than one whole width, so they are never in the same place and the stage is never empty between them.
 */
export const OFF = 130;

/**
 * The whole story as one paused GSAP timeline that is TOTAL units long, so a position is "units of scroll". The scroll drives it with
 * ScrollTrigger (see StoryScroll.tsx); a test can scrub it with `.progress()` and read the picture back. The root holds the markup of World.tsx.
 */
export function buildStoryTimeline(root: HTMLElement, gsap: Gsap, data: StoryData): gsap.core.Timeline {
  const one = (name: string) => root.querySelector<HTMLElement>(`[data-el="${name}"]`) as HTMLElement;
  const all = (name: string) => Array.from(root.querySelectorAll<HTMLElement>(`[data-el="${name}"]`));
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power2.inOut' } });

  const file = one('file');
  const main = one('main');
  const table = one('table');
  const flags = one('flags');
  const checks = one('checks');
  const result = one('result');
  const page = one('page');
  const rows = all('row');
  const kept = rows.filter((row) => row.dataset.kind === 'kept');
  const dropped = rows.filter((row) => row.dataset.kind === 'dropped');
  const cards = all('card');
  const links = all('link');
  const bars = all('bar');
  const captions = all('caption');
  const countEl = one('count');
  const labelEl = one('countLabel');
  const tableCount = one('tableCount');
  const chip = one('chip');
  const flagRows = all('flagRow');
  const flagBars = all('flagBar');
  const flagEnds = all('flagEnd');
  const checkRows = all('checkRow');
  const stamps = all('stamp');
  const tiles = all('tile');
  const typed = one('typed');

  // The first picture: only the file is in view; everything else waits at the side.
  gsap.set([main, flags, checks, result, page], { xPercent: OFF });
  gsap.set(file, { xPercent: 0, y: 24, scale: 0.8, opacity: 1 });
  gsap.set(rows, { opacity: 0, x: -18 });
  gsap.set(one('titleB'), { opacity: 0, y: 8 });
  gsap.set(chip, { opacity: 0 });
  gsap.set(cards, { opacity: 0 });
  gsap.set(root.querySelectorAll('.st-card > *'), { opacity: 0 });
  gsap.set(one('more'), { opacity: 0 });
  gsap.set(links, { strokeDasharray: 1, strokeDashoffset: 1 });
  gsap.set(bars, { scaleY: 0, transformOrigin: '50% 100%' });
  gsap.set(flagRows, { opacity: 0, x: -16 });
  gsap.set(flagBars, { scaleX: 0, transformOrigin: '0% 50%' });
  gsap.set(flagEnds, { opacity: 0, scale: 0 });
  gsap.set(checkRows, { opacity: 0, x: -16 });
  gsap.set(stamps, { opacity: 0, scale: 0.2 });
  gsap.set(tiles, { opacity: 0, y: 18, scale: 0.9 });
  gsap.set(one('lookupCard'), { opacity: 0, y: 16, scale: 0.9 });
  gsap.set(table, { '--hl': 0 });
  countEl.textContent = '0';
  labelEl.textContent = 'fields';
  tableCount.textContent = '0';
  chip.textContent = '1 record';
  typed.textContent = '';
  ['flagN', 'nutN', 'changeN', 'flagCount', 'versionCount', 'checkOk', 'checkBad'].forEach((name) => (one(name).textContent = '0'));
  rows.forEach((row, i) => {
    const pair = data.pairs[i];
    const extra = data.dropped[i - data.pairs.length];
    row.querySelector('dt')!.textContent = pair ? pair.fromKey : (extra?.key ?? '');
    row.querySelector('dd')!.textContent = pair ? pair.fromValue : (extra?.value ?? '');
  });
  // The key lines run from the middle of the cards' box (where the barcode chip is) to the middle of each card.
  const cardsBox = one('cards');
  links.forEach((link, i) => {
    const card = cards[i];
    if (!card || !cardsBox.offsetWidth) return;
    link.setAttribute('x2', `${(((card.offsetLeft + card.offsetWidth / 2) / cardsBox.offsetWidth) * 100).toFixed(1)}%`);
    link.setAttribute('y2', `${(((card.offsetTop + card.offsetHeight / 2) / cardsBox.offsetHeight) * 100).toFixed(1)}%`);
  });

  // 0 to 16: the file rises into view and settles.
  tl.to(file, { y: 0, scale: 1, duration: 10, ease: 'power2.out' }, 0);

  // 16 to 30: the file leaves to the left while the raw table arrives from the right.
  tl.to(file, { xPercent: -OFF * 3.4, duration: 12, ease: 'power3.inOut' }, 16);
  tl.to(main, { xPercent: 0, duration: 12, ease: 'power3.inOut' }, 16);

  // 28 to 40: the rows stream in one by one and the number of fields ticks up to the real count.
  tl.to(rows, { opacity: 1, x: 0, duration: 2.4, stagger: 0.9, ease: 'power2.out' }, 28);
  const fields = { n: 0 };
  tl.to(fields, { n: data.rawFields, duration: 10, ease: 'none', onUpdate: () => (countEl.textContent = String(Math.round(fields.n))) }, 28);
  tl.to(table, { '--hl': 1, duration: 3, ease: 'power1.inOut' }, 37);

  // 40 to 64: the same table is cleaned in place. The title changes, the names and values scramble into their cleaned form;
  // only when the last scramble is done do the fields that are not kept slide out, the table close up and the count tick down.
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
      43 + i * 1.2,
    );
  });
  tl.to(table, { '--hl': 0, duration: 3, ease: 'power1.inOut' }, 52);
  tl.to(dropped, { xPercent: -130, opacity: 0, duration: 2.8, stagger: 1.2, ease: 'power2.in' }, 55);
  tl.to(dropped, { height: 0, paddingTop: 0, paddingBottom: 0, duration: 1.8, stagger: 1.2 }, 56.5);
  const columns = { n: data.rawFields };
  tl.to(
    columns,
    {
      n: data.silverColumns,
      duration: 7.5,
      ease: 'none',
      onUpdate: () => {
        countEl.textContent = String(Math.round(columns.n));
        labelEl.textContent = columns.n === data.rawFields ? 'fields' : 'columns kept';
      },
    },
    56,
  );

  // 64 to 72: the table closes into one record and settles. Nothing else moves until it has.
  tl.to(root.querySelectorAll('.st-fade'), { opacity: 0, duration: 3 }, 64);
  tl.to(table, { scale: 0.2, duration: 6, ease: 'power3.inOut' }, 65);
  tl.to(chip, { opacity: 1, duration: 2 }, 69);
  tl.to(table, { opacity: 0, duration: 2 }, 69.5);

  // 72 to 81: the tables come out of the record one after another. Each starts as a speck at the record, solid and behind it, and grows
  // and slides out to its place; its text shows only once it has grown. The count of tables ticks up as they come out.
  const BURST = 72;
  cards.forEach((card, i) => {
    const start = BURST + i * 1.0;
    tl.fromTo(card, { scale: 0.12, x: () => fromCentre(card, 'x'), y: () => fromCentre(card, 'y') }, { scale: 1, x: 0, y: 0, duration: 6, ease: 'power3.out' }, start);
    tl.fromTo(card, { opacity: 0 }, { opacity: 1, duration: 0.3, ease: 'none', immediateRender: false }, start);
    tl.fromTo(Array.from(card.children), { opacity: 0 }, { opacity: 1, duration: 2.5, stagger: 0.15, ease: 'power1.out', immediateRender: false }, start + 3);
  });
  tl.to(one('more'), { opacity: 1, duration: 2 }, 79.5);
  const tables = { n: 0 };
  tl.to(tables, { n: data.tableCount, duration: 6, ease: 'none', onUpdate: () => (tableCount.textContent = String(Math.round(tables.n))) }, 74);

  // 81 to 91: the record turns into its barcode, and a line is drawn from it to every table: one barcode ties them together.
  const barcode = { t: 0 };
  tl.to(barcode, { t: 1, duration: 3.5, ease: 'none', onUpdate: () => (chip.textContent = scrambleMix('1 record', data.code, barcode.t)) }, 81.5);
  tl.to(links, { strokeDashoffset: 0, duration: 3, stagger: 1, ease: 'power2.inOut' }, 85);

  // 92 to 101: the tables slide out and the long-history product slides in from the right, side by side like a conveyor.
  conveyor(tl, main, flags, 92, 9);

  // 101 to 127: its flags stream in as rows (with the versions and the flags ticking up), then each row grows a bar from the day the flag first appeared to the day it ended.
  tl.to(flagRows, { opacity: 1, x: 0, duration: 2, stagger: 1, ease: 'power2.out' }, 101);
  const versions = { n: 0 };
  tl.to(versions, { n: data.history.versions, duration: 8, ease: 'none', onUpdate: () => (one('versionCount').textContent = String(Math.round(versions.n))) }, 101);
  const flagTotal = { n: 0 };
  tl.to(flagTotal, { n: data.history.flagCount, duration: 9, ease: 'none', onUpdate: () => (one('flagCount').textContent = String(Math.round(flagTotal.n))) }, 101);
  tl.to(flagBars, { scaleX: 1, duration: 4, stagger: 1.1, ease: 'power2.out' }, 112);
  tl.to(flagEnds, { opacity: 1, scale: 1, duration: 1, stagger: 1.1, ease: 'back.out(2)' }, 115.5);

  // 127 to 135: on to the product whose figures disagree with some of the rules.
  conveyor(tl, flags, checks, 127, 8);

  // 135 to 148: the rule rows stream in, and each gets a stamp (agrees or does not agree) while the two counters tick.
  tl.to(checkRows, { opacity: 1, x: 0, duration: 1.5, stagger: 0.6, ease: 'power2.out' }, 135);
  tl.to(stamps, { opacity: 1, scale: 1, duration: 1, stagger: 0.7, ease: 'back.out(2.2)' }, 138);
  const landed = { n: 0 };
  const rules = data.checks.rows;
  tl.to(
    landed,
    {
      n: rules.length,
      duration: rules.length * 0.7,
      ease: 'none',
      onUpdate: () => {
        const done = Math.min(rules.length, Math.floor(landed.n + 1e-6));
        one('checkOk').textContent = String(rules.slice(0, done).filter((r) => r.ok).length);
        one('checkBad').textContent = String(rules.slice(0, done).filter((r) => !r.ok).length);
      },
    },
    138,
  );

  // 148 to 160: the chart and the product card slide in; the bars grow and the figures count up.
  conveyor(tl, checks, result, 148, 8);
  tl.to(bars, { scaleY: 1, duration: 2, stagger: 0.3, ease: 'power2.out' }, 157);
  (
    [
      ['flagN', data.flagRows],
      ['nutN', data.nutritionRows],
      ['changeN', data.changeRows],
    ] as const
  ).forEach(([name, target], i) => {
    const counter = { n: 0 };
    tl.to(counter, { n: target, duration: 3.5, ease: 'none', onUpdate: () => (one(name).textContent = String(countAt(0, target, counter.n / (target || 1)))) }, 157 + i * 0.3);
  });

  // 161 to 180: the page slides in and builds itself: the four tiles pop in, a barcode is typed into the search box, and its card appears.
  conveyor(tl, result, page, 161, 7);
  tl.to(tiles, { opacity: 1, y: 0, scale: 1, duration: 1.5, stagger: 0.6, ease: 'back.out(1.6)' }, 169);
  const typing = { n: 0 };
  tl.to(
    typing,
    {
      n: data.code.length,
      duration: 5,
      ease: 'none',
      onUpdate: () => {
        const n = Math.round(typing.n);
        typed.textContent = data.code.slice(0, n) + (n > 0 && n < data.code.length ? '│' : '');
      },
    },
    172,
  );
  tl.to(one('lookupCard'), { opacity: 1, y: 0, scale: 1, duration: 3, ease: 'back.out(1.4)' }, 177);

  // The captions take turns in one place.
  captions.forEach((caption, i) => {
    const { from, to } = BEATS[i];
    gsap.set(caption, { opacity: i === 0 ? 1 : 0 });
    if (i > 0) tl.fromTo(caption, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 3, ease: 'power1.out' }, from);
    if (i < captions.length - 1) tl.to(caption, { opacity: 0, y: -14, duration: 3, ease: 'power1.in' }, to - 3);
  });

  // A thin bar along the foot of the stage shows how far through the story the scroll is.
  tl.fromTo(one('progress'), { scaleX: 0 }, { scaleX: 1, duration: TOTAL, ease: 'none' }, 0);

  tl.set({}, {}, TOTAL); // the timeline is exactly TOTAL units long
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
