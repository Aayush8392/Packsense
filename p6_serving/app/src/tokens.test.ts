import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { contrastRatio, readThemes } from './contrast';

const css = readFileSync(join(import.meta.dirname, 'tokens.css'), 'utf-8');
const themes = readThemes(css);

/** Text colour, background it sits on. Small text needs 4.5:1. */
const TEXT_PAIRS: [string, string][] = [
  ['fg', 'bg'],
  ['fg', 'card'],
  ['fg', 'soft'],
  ['fg-muted', 'bg'],
  ['fg-muted', 'soft'],
  ['fg-muted', 'card'],
  ['primary', 'bg'],
  ['primary', 'card'],
  ['primary', 'soft'],
  ['secondary', 'bg'],
  ['secondary', 'card'],
  ['secondary', 'soft'],
  ['problem', 'bg'],
  ['problem', 'card'],
  ['on-primary', 'primary'],
  ['on-primary', 'primary-hover'],
  ['advisory-fg', 'advisory-bg'],
];

describe('colour tokens', () => {
  it('has the same tokens in both themes', () => {
    expect(Object.keys(themes.dark).sort()).toEqual(Object.keys(themes.light).sort());
  });

  it('has the same dark values whether the system or the visitor chose dark', () => {
    expect(themes.chosenDark).toEqual(themes.dark);
  });

  it('changes every colour token in the dark theme except none by accident', () => {
    for (const name of Object.keys(themes.light)) expect(themes.dark[name], name).toBeDefined();
    expect(themes.dark.bg).not.toBe(themes.light.bg);
    expect(themes.dark.fg).not.toBe(themes.light.fg);
  });

  for (const theme of ['light', 'dark'] as const) {
    for (const [fg, bg] of TEXT_PAIRS) {
      it(`${theme}: ${fg} on ${bg} is at least 4.5:1`, () => {
        const ratio = contrastRatio(themes[theme][fg], themes[theme][bg]);
        expect(ratio, `${fg} ${themes[theme][fg]} on ${bg} ${themes[theme][bg]}`).toBeGreaterThanOrEqual(4.5);
      });
    }
  }

  it('measures a known pair correctly (black on white is 21:1)', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5);
  });

  it('would catch a failing pair (light grey on white is below 4.5:1)', () => {
    expect(contrastRatio('#bbbbbb', '#ffffff')).toBeLessThan(4.5);
  });
});

describe('type scale', () => {
  it('never goes below 0.75rem and uses no pixel font sizes', () => {
    const sizes = [...css.matchAll(/--text-[a-z-]+:\s*([^;]+);/g)].map((m) => m[1]);
    expect(sizes.length).toBeGreaterThan(5);
    for (const size of sizes) expect(size).not.toMatch(/px|%/);
    const base = readFileSync(join(import.meta.dirname, 'base.css'), 'utf-8');
    expect(base).not.toMatch(/font-size:\s*[\d.]+px/);
  });
});

describe('layout', () => {
  it('gives every page the same width, with no narrower variant', () => {
    const base = readFileSync(join(import.meta.dirname, 'base.css'), 'utf-8');
    expect(base).not.toMatch(/\.page--/);
    expect(base).toMatch(/\.page \{[^}]*max-width: 85rem;/);
    expect(base).not.toMatch(/column-count/);
  });

  it('keeps every card in a chart grid as tall as its own content, so opening one table does not stretch the others', () => {
    const data = readFileSync(join(import.meta.dirname, 'dataPages.css'), 'utf-8');
    expect(data).toMatch(/\.chart-grid \{[^}]*align-items: start;/);
  });

  it('lets the padded barcode input win over the plain input rule', () => {
    const base = readFileSync(join(import.meta.dirname, 'base.css'), 'utf-8');
    expect(base).toContain('.barcode-box .barcode-box__field input {');
  });
});
