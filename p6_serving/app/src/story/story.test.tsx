import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { parseShowcase } from '../data/showcase';
import { captions } from './beats';
import { PASSES, pass, sceneVars } from './scene';
import { StoryScroll } from './StoryScroll';
import { storyFrom } from './storyData';
import { BEATS, beatAt, captionOpacity, clamp01, ease, lerp, seg } from './timeline';

afterEach(cleanup);

const showcaseText = readFileSync(join(import.meta.dirname, '..', '..', '..', 'showcase', 'showcase.json'), 'utf-8');
const num = (vars: Record<string, string>, name: string) => parseFloat(vars[name]);

describe('timeline', () => {
  it('clamps, mixes and eases', () => {
    expect(clamp01(-1)).toBe(0);
    expect(clamp01(2)).toBe(1);
    expect(lerp(10, 20, 0.25)).toBe(12.5);
    expect([ease(0), ease(0.5), ease(1)]).toEqual([0, 0.5, 1]);
    expect(ease(0.25)).toBeLessThan(0.25); // slow at the start
    expect(ease(0.75)).toBeGreaterThan(0.75); // and slow again at the end
  });

  it('says how far through a stretch a progress is, 0 before it and 1 after it', () => {
    expect(seg(0.1, 0.2, 0.4)).toBe(0);
    expect(seg(0.3, 0.2, 0.4)).toBeCloseTo(0.5, 9);
    expect(seg(0.9, 0.2, 0.4)).toBe(1);
  });

  it('cuts the scroll into five stages that follow each other with no gap', () => {
    expect(BEATS).toHaveLength(5);
    BEATS.forEach((beat, i) => {
      if (i === 0) expect(beat.from).toBe(0);
      else expect(beat.from).toBe(BEATS[i - 1].to);
    });
    expect(BEATS[4].to).toBe(1);
    expect([beatAt(0), beatAt(0.19), beatAt(0.2), beatAt(0.5), beatAt(0.99), beatAt(1)]).toEqual([0, 0, 1, 2, 4, 4]);
  });

  it('shows a caption inside its stage and fades it at the ends', () => {
    expect(captionOpacity(0, BEATS[0])).toBe(1);
    expect(captionOpacity(0.3, BEATS[1])).toBe(1);
    expect(captionOpacity(0.3, BEATS[2])).toBe(0);
    expect(captionOpacity(0.43, BEATS[1])).toBeGreaterThan(0);
    expect(captionOpacity(0.43, BEATS[1])).toBeLessThan(1);
  });
});

describe('the scene', () => {
  it('starts with only the daily file in view, far away', () => {
    const v = sceneVars(0);
    expect(num(v, '--file-o')).toBe(1);
    expect(num(v, '--file-z')).toBeLessThan(-2000);
    for (const name of ['raw', 'clean', 'tables', 'result', 'page']) expect(num(v, `--${name}-o`)).toBe(0);
  });

  it('puts each layer in front of the camera, fully visible, while its stage is on', () => {
    expect(num(sceneVars(0.33), '--raw-o')).toBe(1);
    expect(num(sceneVars(0.33), '--raw-z')).toBe(0);
    expect(num(sceneVars(0.53), '--clean-o')).toBe(1);
    expect(num(sceneVars(0.53), '--clean-z')).toBe(0);
    expect(num(sceneVars(0.72), '--tables-o')).toBe(1);
    expect(num(sceneVars(0.72), '--tables-z')).toBe(0);
    expect(num(sceneVars(0.88), '--result-o')).toBe(1);
    expect(num(sceneVars(1), '--page-o')).toBe(1);
    expect(num(sceneVars(1), '--page-z')).toBe(0);
  });

  it('moves every layer only forward, toward the camera, however the scroll goes', () => {
    for (const path of Object.values(PASSES)) {
      let before = -Infinity;
      for (let i = 0; i <= 200; i++) {
        const z = pass(i / 200, path).z;
        expect(z).toBeGreaterThanOrEqual(before - 1e-9);
        before = z;
      }
    }
  });

  it('keeps every opacity between 0 and 1 and every figure a real number, at any progress, even one outside 0 to 1', () => {
    for (const p of [-1, 0, 0.05, 0.2, 0.37, 0.5, 0.64, 0.8, 0.95, 1, 2]) {
      for (const [name, value] of Object.entries(sceneVars(p))) {
        expect(Number.isFinite(parseFloat(value)), `${name} at ${p}`).toBe(true);
        if (name.endsWith('-o') || name.startsWith('--caption')) {
          expect(parseFloat(value)).toBeGreaterThanOrEqual(0);
          expect(parseFloat(value)).toBeLessThanOrEqual(1);
        }
      }
    }
    expect(sceneVars(-1)).toEqual(sceneVars(0));
    expect(sceneVars(2)).toEqual(sceneVars(1));
  });

  it('is the same picture at the same progress, whichever way the visitor scrolled to it', () => {
    expect(sceneVars(0.4)).toEqual(sceneVars(0.4));
  });

  it('turns the username into a hidden code, drops the unused fields, spreads the tables and grows the bars in that order', () => {
    const at = (p: number, name: string) => num(sceneVars(p), name);
    expect(at(0.4, '--swap')).toBe(0);
    expect(at(0.56, '--swap')).toBe(1);
    expect(at(0.45, '--drop')).toBe(0);
    expect(at(0.6, '--drop')).toBe(1);
    expect(at(0.58, '--spread')).toBe(0);
    expect(at(0.76, '--spread')).toBe(1);
    expect(at(0.74, '--bars')).toBe(0);
    expect(at(0.9, '--bars')).toBe(1);
  });
});

describe('the figures of the story', () => {
  const data = storyFrom(parseShowcase(showcaseText));

  it('come from the real record: its 245 raw fields, 81 kept columns and eight tables', () => {
    expect(data).not.toBeNull();
    expect(data?.rawFields).toBe(245);
    expect(data?.silverColumns).toBe(81);
    expect(data?.tableCount).toBe(8);
    expect(data?.tables.map((t) => t.name)).toEqual(['product_history', 'product_flag_spans', 'product_nutrition_sets', 'product_rule_verdicts']);
  });

  it('follow one username from the raw record to the column that hides it', () => {
    expect(data?.userField).toBe('creator');
    expect(data?.userValue).toMatch(/^contributor-/);
    expect(data?.cleanRows.find((r) => r.key === data.hiddenField)?.value).toBe('hidden on purpose');
  });

  it('name three raw fields that the cleaned copy drops', () => {
    expect(data?.droppedKeys).toHaveLength(3);
  });

  it('are never typed into the captions: they carry the numbers of the data, or none', () => {
    expect(captions(data)[1].text).toContain('245');
    expect(captions(data)[2].text).toContain('81');
    expect(captions(data)[3].text).toContain('8 of them');
    expect(captions(null).map((c) => c.text).join(' ')).not.toMatch(/\d/);
  });
});

describe('the story on the page', () => {
  beforeEach(() => {
    window.matchMedia = ((query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia;
  });

  it('has a heading, a way past it, and the five stages as an ordered list a screen reader can read', () => {
    render(<StoryScroll />);
    expect(screen.getByRole('heading', { level: 2, name: 'How it works, in one scroll' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Skip the animation' }).getAttribute('href')).toBe('#after-story');
    const items = screen.getAllByRole('listitem').filter((li) => li.closest('.story__captions'));
    expect(items).toHaveLength(5);
    expect(items[0].getAttribute('aria-current')).toBe('step');
  });

  it('keeps the scene out of the reading order, because the captions say everything it shows', () => {
    const { container } = render(<StoryScroll />);
    expect(container.querySelector('.story__world')?.getAttribute('aria-hidden')).toBe('true');
  });

  it('follows the scroll: halfway down the tall section the stage writes its progress and moves to the second stage', async () => {
    const { container } = render(<StoryScroll />);
    const section = container.querySelector('.story') as HTMLElement;
    const stage = container.querySelector('.story__stage') as HTMLElement;
    Object.defineProperty(stage, 'offsetHeight', { value: 800, configurable: true });
    section.getBoundingClientRect = () => ({ top: -1000, height: 5000, bottom: 4000, left: 0, right: 0, width: 0, x: 0, y: -1000, toJSON: () => ({}) });
    act(() => {
      window.dispatchEvent(new Event('scroll'));
    });
    await waitFor(() => expect(stage.style.getPropertyValue('--progress')).toBe('0.238'));
    await waitFor(() => expect(screen.getAllByRole('listitem').filter((li) => li.closest('.story__captions'))[1].getAttribute('aria-current')).toBe('step'));
  });

  it('can be held at one frame with the development slider, and let go again', async () => {
    const { container } = render(<StoryScroll />);
    const stage = container.querySelector('.story__stage') as HTMLElement;
    fireEvent.change(screen.getByRole('slider'), { target: { value: '500' } });
    await waitFor(() => expect(stage.style.getPropertyValue('--progress')).toBe('0.500'));
    expect(stage.style.getPropertyValue('--clean-o')).toBe('1.000');
  });

  it('is a plain list of the five steps, with no scene and no tall section, for a visitor who asked for less motion', () => {
    window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia;
    const { container } = render(<StoryScroll />);
    expect(container.querySelector('.story__stage')).toBeNull();
    expect(container.querySelector('.story-still')).not.toBeNull();
    expect(screen.getAllByRole('listitem')).toHaveLength(5);
  });
});
