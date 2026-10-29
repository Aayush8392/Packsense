import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { frameTables, parsePage, splitBlocks } from './parse';

const DIR = join(import.meta.dirname, '..', '..', 'content');
const files = readdirSync(DIR).filter((name) => name.endsWith('.md')).sort();
const pages = files.map((name) => parsePage(name, readFileSync(join(DIR, name), 'utf-8')));

describe('content loader on the real page texts', () => {
  it('reads all twelve files, in order, with unique slugs', () => {
    expect(pages).toHaveLength(12);
    expect(pages.map((p) => p.meta.order)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    expect(new Set(pages.map((p) => p.meta.slug)).size).toBe(12);
  });

  it('gives every page exactly one heading line, and none in the rendered text', () => {
    for (const page of pages) {
      expect(page.text.match(/^# /gm), page.fileName).toHaveLength(1);
      expect(page.html, page.fileName).not.toContain('<h1');
    }
  });

  const differ = pages.find((p) => p.meta.slug === 'how-we-differ');

  it('renders page 02 with its table and its eleven numbered checks', () => {
    expect(differ).toBeDefined();
    expect(differ?.html).toContain('<table role="table">');
    const checks = differ?.html.match(/<li>/g) ?? [];
    expect(checks).toHaveLength(11);
  });

  it('keeps every claim that was fact-checked in the text of page 02', () => {
    expect(differ?.meta.checked_claims).toHaveLength(3);
    for (const claim of differ?.meta.checked_claims ?? []) expect(differ?.text).toContain(claim);
  });

  it('does not show the notes meant for the designer', () => {
    for (const page of pages) {
      for (const note of page.meta.design_notes ?? []) expect(page.html).not.toContain(note.slice(0, 40));
    }
  });
});

describe('page layout helpers', () => {
  it('takes the heading out of the body, so the template can frame it', () => {
    for (const page of pages) {
      expect(page.heading.length, page.fileName).toBeGreaterThan(0);
      expect(page.html, page.fileName).not.toContain('<h1');
    }
  });

  it('frames a table as a card with row headers and a marked last column', () => {
    const html = frameTables('<table><thead><tr><th>Q</th><th>A</th><th>B</th></tr></thead><tbody><tr><td>one</td><td>two</td><td>three</td></tr></tbody></table>');
    expect(html).toContain('<div class="table-card">');
    expect(html).toContain('<th role="rowheader" scope="row">one</th>');
    expect(html).toContain('<td role="cell" data-label="A">two</td>');
    expect(html).toContain('<td role="cell" data-label="B" class="col-emph">three</td>');
    expect(html).toContain('<th role="columnheader" class="col-emph">B</th>');
    expect(html).not.toContain('data-label="A" class="col-emph"');
  });

  it('frames the comparison table of page 02 with eight row headers', () => {
    const differ = pages.find((p) => p.meta.slug === 'how-we-differ');
    expect(differ?.html.match(/scope="row"/g)).toHaveLength(8);
    expect(differ?.html.match(/data-label="What OFF gives you"/g)).toHaveLength(8);
  });

  it('turns the bold lead-in paragraphs after the first heading into callouts, and only those', () => {
    const differ = pages.find((p) => p.meta.slug === 'how-we-differ');
    const titles = [...(differ?.html.matchAll(/<aside class="callout"><h3>([^<]+)<\/h3>/g) ?? [])].map((m) => m[1]);
    expect(titles).toEqual(['What PackSense does not claim', 'This copy is not OFF']);
    expect(differ?.html).toContain('<p><strong>What OFF is good at.</strong>');
    const home = pages.find((p) => p.meta.slug === 'home');
    expect(home?.html).not.toContain('class="callout"');
  });

  it('splits the home text into its blocks', () => {
    const home = pages.find((p) => p.meta.slug === 'home');
    const blocks = splitBlocks(home?.html ?? '');
    expect(blocks.filter((b) => b.startsWith('<h2>'))).toHaveLength(1);
    expect(blocks.filter((b) => b.startsWith('<ul>'))).toHaveLength(1);
    expect(blocks.some((b) => b.includes('<strong>What PackSense does not do.'))).toBe(true);
    expect(blocks.some((b) => b.includes('<strong>Small print.'))).toBe(true);
  });
});

describe('parsePage', () => {
  it('refuses a file with no front matter', () => {
    expect(() => parsePage('x.md', '# Just text')).toThrow(/front matter missing/);
  });

  it('refuses front matter without a slug', () => {
    expect(() => parsePage('x.md', '---\ntitle: T\nsection: S\norder: 1\n---\nbody')).toThrow(/slug/);
  });
});
