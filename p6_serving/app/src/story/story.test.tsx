import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { gsap } from 'gsap';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { parseShowcase } from '../data/showcase';
import { captions } from './beats';
import { GROUPS, OFF, buildStoryTimeline } from './motion';
import { StoryScroll, StoryStage, StoryStill, World } from './StoryScroll';
import { storyFrom, type StoryData } from './storyData';
import { countAt, scrambleMix } from './text';
import { BEATS, beatAt, clamp01, lerp } from './timeline';

afterEach(cleanup);

const showcaseText = readFileSync(join(import.meta.dirname, '..', '..', '..', 'showcase', 'showcase.json'), 'utf-8');
const data = storyFrom(parseShowcase(showcaseText)) as StoryData;

describe('timeline helpers', () => {
  it('clamps and mixes', () => {
    expect(clamp01(-1)).toBe(0);
    expect(clamp01(2)).toBe(1);
    expect(lerp(10, 20, 0.25)).toBe(12.5);
  });

  it('cuts the scroll into five stages that follow each other with no gap, in percent', () => {
    expect(BEATS).toHaveLength(5);
    BEATS.forEach((beat, i) => expect(beat.from).toBe(i === 0 ? 0 : BEATS[i - 1].to));
    expect(BEATS[4].to).toBe(100);
    expect([beatAt(0), beatAt(15), beatAt(16), beatAt(50), beatAt(99), beatAt(100)]).toEqual([0, 0, 1, 2, 4, 4]);
  });
});

describe('text that changes as you scroll', () => {
  it('scrambles one text into another: the old at 0, the new at 1, the same mix at the same step', () => {
    expect(scrambleMix('contributor-A', 'hidden on purpose', 0)).toBe('contributor-A');
    expect(scrambleMix('contributor-A', 'hidden on purpose', 1)).toBe('hidden on purpose');
    expect(scrambleMix('contributor-A', 'hidden on purpose', 0.4)).toBe(scrambleMix('contributor-A', 'hidden on purpose', 0.4));
  });

  it('settles the new letters from the left, and the length slides from the old length to the new', () => {
    const half = scrambleMix('abcdefghij', 'XY', 0.5);
    expect(half.startsWith('X')).toBe(true);
    expect(half).toHaveLength(6);
    expect(scrambleMix('ab', 'hidden on purpose', 0.5)).toHaveLength(Math.round((2 + 17) / 2));
  });

  it('counts whole numbers between two values', () => {
    expect([countAt(245, 81, 0), countAt(245, 81, 0.5), countAt(245, 81, 1), countAt(245, 81, 2)]).toEqual([245, 163, 81, 81]);
  });
});

describe('the figures of the story', () => {
  it('come from the real record: 245 raw fields, 81 kept columns and eight tables', () => {
    expect(data.rawFields).toBe(245);
    expect(data.silverColumns).toBe(81);
    expect(data.tableCount).toBe(8);
    expect(data.tables.map((t) => t.name)).toEqual(['product_history', 'product_flag_spans', 'product_nutrition_sets', 'product_rule_verdicts']);
  });

  it('follow one username from the raw record to the column that hides it', () => {
    const user = data.pairs.find((pair) => pair.user);
    expect(user?.fromKey).toBe('creator');
    expect(user?.fromValue).toMatch(/^contributor-/);
    expect(user?.toKey).toBe('creator_hmac');
    expect(user?.toValue).toBe('hidden on purpose');
  });

  it('keep five fields (renamed on the way) and drop three that the cleaned copy does not have', () => {
    expect(data.pairs).toHaveLength(5);
    expect(data.dropped).toHaveLength(3);
  });

  it('are never typed into the captions: they carry the numbers of the data, or none', () => {
    expect(captions(data)[1].text).toContain('245');
    expect(captions(data)[2].text).toContain('81');
    expect(captions(data)[3].text).toContain('8 of them');
    expect(captions(null).map((c) => c.text).join(' ')).not.toMatch(/\d/);
  });
});

describe('the timeline', () => {
  function stage() {
    const { container } = render(
      <div className="story__stage">
        <World data={data} />
        <ol>
          {captions(data).map((c) => (
            <li key={c.title} data-el="caption" />
          ))}
        </ol>
      </div>,
    );
    const root = container.firstElementChild as HTMLElement;
    const tl = buildStoryTimeline(root, gsap, data);
    const at = (p: number) => tl.progress(p, false);
    const text = (name: string) => root.querySelector(`[data-el="${name}"]`)?.textContent;
    const group = (name: string) => root.querySelector(`[data-group="${name}"]`) as HTMLElement;
    return { root, tl, at, text, group };
  }
  const read = (el: HTMLElement) => ({ opacity: Number(gsap.getProperty(el, 'opacity')), x: Number(gsap.getProperty(el, 'xPercent')) });

  it('is exactly 100 units long, so a position is a percent of the scroll', () => {
    expect(stage().tl.duration()).toBe(100);
  });

  it('starts with only the file in view and the rest waiting at the side', () => {
    const { at, group } = stage();
    at(0);
    expect(read(group('file')).x).toBe(0);
    for (const name of ['main', 'result', 'page']) expect(read(group(name)).x).toBe(OFF);
  });

  it('never has two things on the stage at once: any two that are in view are at least a whole width apart', () => {
    const { at, group } = stage();
    for (let p = 0; p <= 1.0001; p += 0.005) {
      at(Math.min(p, 1));
      const inView = GROUPS.map((name) => ({ name, ...read(group(name)) })).filter((g) => g.opacity > 0.02 && Math.abs(g.x) < OFF * 0.88);
      for (let i = 0; i < inView.length; i++) {
        for (let j = i + 1; j < inView.length; j++) {
          expect(Math.abs(inView[i].x - inView[j].x), `${inView[i].name} and ${inView[j].name} at ${p.toFixed(3)}`).toBeGreaterThanOrEqual(100);
        }
      }
    }
  });

  it('ends on the page, centred, and every other thing off to the left', () => {
    const { at, group } = stage();
    at(1);
    expect(read(group('page')).x).toBe(0);
    for (const name of ['file', 'main', 'result']) expect(read(group(name)).x).toBeLessThan(-OFF * 0.9);
  });

  it('ticks the field count up to 245 as the rows stream in, and back down to 81 as the table is cleaned', () => {
    const { at, text } = stage();
    at(0.3);
    expect(Number(text('count'))).toBeGreaterThan(0);
    expect(Number(text('count'))).toBeLessThan(245);
    at(0.39);
    expect(text('count')).toBe('245');
    expect(text('countLabel')).toBe('fields');
    at(0.55);
    expect(Number(text('count'))).toBeLessThan(245);
    expect(Number(text('count'))).toBeGreaterThan(81);
    at(0.62);
    expect(text('count')).toBe('81');
    expect(text('countLabel')).toBe('columns kept');
  });

  it('scrambles the username into "hidden on purpose" in the same row', () => {
    const { at, root } = stage();
    const value = () => (root.querySelectorAll('[data-kind="kept"]')[2].querySelector('dd') as HTMLElement).textContent;
    const key = () => (root.querySelectorAll('[data-kind="kept"]')[2].querySelector('dt') as HTMLElement).textContent;
    at(0.4);
    expect([key(), value()]).toEqual(['creator', 'contributor-A']);
    at(0.5);
    expect(value()).not.toBe('contributor-A');
    expect(value()).not.toBe('hidden on purpose');
    at(0.62);
    expect([key(), value()]).toEqual(['creator_hmac', 'hidden on purpose']);
  });

  it('slides the dropped rows out, one after another, and closes the table up', () => {
    const { at, root } = stage();
    const dropped = Array.from(root.querySelectorAll<HTMLElement>('[data-kind="dropped"]'));
    at(0.49);
    dropped.forEach((row) => expect(Number(gsap.getProperty(row, 'opacity'))).toBe(1));
    at(0.62);
    dropped.forEach((row) => expect(Number(gsap.getProperty(row, 'opacity'))).toBe(0));
  });

  it('counts the tables up to eight and the chart figures up to the real rows', () => {
    const { at, text } = stage();
    at(0.5);
    expect(text('tableCount')).toBe('0');
    at(0.78);
    expect(text('tableCount')).toBe('8');
    at(0.96);
    expect(text('flagN')).toBe(String(data.flagRows));
    expect(text('nutN')).toBe(String(data.nutritionRows));
    expect(text('changeN')).toBe(String(data.changeRows));
  });

  it('shows one caption at a time, in order', () => {
    const { at, root } = stage();
    const caps = Array.from(root.querySelectorAll<HTMLElement>('[data-el="caption"]'));
    const visible = () => caps.map((c, i) => [i, Number(gsap.getProperty(c, 'opacity'))] as const).filter(([, o]) => o > 0.5).map(([i]) => i);
    for (const [p, beat] of [[0.05, 0], [0.28, 1], [0.52, 2], [0.74, 3], [0.95, 4]] as const) {
      at(p);
      expect(visible()).toEqual([beat]);
    }
  });

  it('is the same picture at the same place, whichever way you scrolled to it', () => {
    const a = stage();
    const snapshot = (s: ReturnType<typeof stage>) => [s.text('count'), s.text('countLabel'), s.text('tableCount'), s.text('flagN'), s.root.querySelector('[data-kind="kept"] dd')?.textContent, ...GROUPS.map((g) => JSON.stringify(read(s.group(g))))].join('|');
    a.at(0.2);
    a.at(0.9);
    a.at(0.5);
    const forwardThenBack = snapshot(a);
    cleanup();
    const b = stage();
    b.at(0.1);
    b.at(0.5);
    expect(snapshot(b)).toBe(forwardThenBack);
  });
});

describe('the story on the page', () => {
  beforeEach(() => {
    window.matchMedia = ((query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia;
  });

  it('has a heading, a way past it, and the five stages as an ordered list a screen reader can read', async () => {
    let ready = false;
    render(<StoryStage data={data} onReady={() => (ready = true)} />);
    await waitFor(() => expect(ready).toBe(true));
    expect(screen.getByRole('heading', { level: 2, name: 'How it works, in one scroll' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Skip the animation' }).getAttribute('href')).toBe('#after-story');
    const items = screen.getAllByRole('listitem').filter((li) => li.closest('.story__captions'));
    expect(items).toHaveLength(5);
    expect(items[0].getAttribute('aria-current')).toBe('step');
  });

  it('keeps the scene out of the reading order, because the captions say everything it shows', () => {
    const { container } = render(<StoryStage data={data} />);
    expect(container.querySelector('.story__world')?.getAttribute('aria-hidden')).toBe('true');
  });

  it('can be held at one frame with the development slider, and moves to that stage', async () => {
    let ready = false;
    const { container } = render(<StoryStage data={data} onReady={() => (ready = true)} />);
    await waitFor(() => expect(ready).toBe(true));
    fireEvent.change(screen.getByRole('slider'), { target: { value: '500' } });
    await waitFor(() => expect(screen.getAllByRole('listitem').filter((li) => li.closest('.story__captions'))[2].getAttribute('aria-current')).toBe('step'));
    expect(container.querySelector('[data-el="count"]')?.textContent).not.toBe('0');
  });

  it('is a plain list of the five steps, with no scene and no tall section, for a visitor who asked for less motion', () => {
    window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia;
    const { container } = render(<StoryScroll />);
    expect(container.querySelector('.story__stage')).toBeNull();
    expect(container.querySelector('.story-still')).not.toBeNull();
    expect(screen.getAllByRole('listitem')).toHaveLength(5);
  });

  it('is the same plain list when the figures cannot be loaded', async () => {
    const { container } = render(<StoryScroll />);
    await waitFor(() => expect(container.querySelector('.story-still')).not.toBeNull(), { timeout: 3000 });
    expect(container.querySelector('.story__stage')).toBeNull();
  });

  it('the plain list carries the same words, with no figure when there is no data', () => {
    render(<StoryStill data={null} />);
    expect(screen.getByRole('heading', { level: 2, name: 'How it works, in five steps' })).toBeTruthy();
  });
});
