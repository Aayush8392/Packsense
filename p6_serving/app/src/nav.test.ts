import { describe, expect, it } from 'vitest';
import { PAGES } from './content';
import { FOLDED_SLUGS, NAV_PAGES, TABS, pageForPath, pagesInTab } from './nav';

describe('navigation', () => {
  it('routes every page text except the two that are folded into other pages', () => {
    const routed = new Set(NAV_PAGES.map((p) => p.slug));
    const all = PAGES.map((p) => p.meta.slug);
    expect(all.filter((slug) => !routed.has(slug)).sort()).toEqual([...FOLDED_SLUGS].sort());
    for (const slug of routed) expect(all, slug).toContain(slug);
  });

  it('uses each address once', () => {
    expect(new Set(NAV_PAGES.map((p) => p.path)).size).toBe(NAV_PAGES.length);
  });

  it('has six tabs, each with at least one page, and each tab link goes to one of its pages', () => {
    expect(TABS).toHaveLength(6);
    for (const tab of TABS) {
      expect(pagesInTab(tab.id).length, tab.id).toBeGreaterThan(0);
      expect(pageForPath(tab.path)?.tab, tab.id).toBe(tab.id);
    }
  });

  it('matches the section named in each page text', () => {
    const sectionOf = { home: 'Home', explore: 'Explore the data', how: 'How it works', data: 'Get the data', lookup: 'Look up', about: 'About' };
    for (const nav of NAV_PAGES) {
      const page = PAGES.find((p) => p.meta.slug === nav.slug);
      expect(page?.meta.section, nav.slug).toBe(sectionOf[nav.tab]);
    }
  });

  it('finds a page with or without a trailing slash', () => {
    expect(pageForPath('/explore/brands/')?.slug).toBe('brands');
    expect(pageForPath('/')?.slug).toBe('home');
    expect(pageForPath('/nowhere')).toBeUndefined();
  });
});
