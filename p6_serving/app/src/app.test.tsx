import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import axe from 'axe-core';
import { createMemoryRouter } from 'react-router';
import { RouterProvider } from 'react-router/dom';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { changeDaily, pipelineHealth, qualityDaily, siteStatus } from './data/siteData';
import { NAV_PAGES } from './nav';
import { routes } from './routes';

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return { router, ...render(<RouterProvider router={router} />) };
}

const fixture = (name: string) => readFileSync(join(import.meta.dirname, 'data', 'fixtures', name), 'utf-8');

// Most tests do not need the data files: every file answers "not found", and the page shows its dashes and a plain notice.
function serveFiles(files: Record<string, string> = {}) {
  vi.stubGlobal('fetch', async (url: string) => {
    const name = String(url).split('/').pop() ?? '';
    return name in files ? new Response(files[name], { status: 200 }) : new Response('', { status: 404 });
  });
}

beforeAll(() => {
  window.scrollTo = () => {};
  (globalThis as { __BUILD_TIME__?: string }).__BUILD_TIME__ ??= '2026-10-29T12:00:00.000Z';
});
beforeEach(() => {
  serveFiles();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  for (const resource of [siteStatus, changeDaily, pipelineHealth, qualityDaily]) resource.reset();
});

describe('page 02 end to end', () => {
  it('shows the page text under one h1, with the landmarks, the credit and the build time', () => {
    renderAt('/how-it-works/differences');
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('How PackSense differs from Open Food Facts');
    expect(screen.getByRole('banner')).toBeTruthy();
    expect(screen.getByRole('main')).toBeTruthy();
    expect(screen.getByRole('contentinfo').textContent).toContain('Open Database License');
    expect(screen.getByRole('contentinfo').textContent).toContain('Site built');
    expect(screen.getAllByRole('table')).toHaveLength(1);
    expect(document.title).toBe('How PackSense differs from Open Food Facts — PackSense');
  });

  it('marks the current tab, shows the second-level row and a breadcrumb', () => {
    renderAt('/how-it-works/differences');
    const main = screen.getByRole('navigation', { name: 'Main' });
    expect(within(main).getByRole('link', { name: 'How it works' }).getAttribute('aria-current')).toBe('page');
    const sub = screen.getByRole('navigation', { name: 'How it works pages' });
    expect(within(sub).getAllByRole('link').map((a) => a.textContent)).toEqual([
      'How PackSense works',
      'How PackSense differs',
      'Pipeline health',
    ]);
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(crumbs.textContent).toContain('How PackSense differs');
  });

  it('has no accessibility violations that jsdom can detect', async () => {
    const { container } = renderAt('/how-it-works/differences');
    // Colour contrast needs real rendering: it is covered by tokens.test.ts instead.
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });
});

describe('menu on small screens', () => {
  it('opens and closes with the button and with Escape, and Escape returns focus to the button', () => {
    renderAt('/');
    const button = screen.getByRole('button', { name: 'Menu' });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(button.getAttribute('aria-controls')).toBe('site-menu');
    fireEvent.click(button);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(document.getElementById('site-menu')?.getAttribute('data-open')).toBe('true');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(button);
  });

  it('closes after choosing a link', async () => {
    const { router } = renderAt('/');
    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'About' }));
    await screen.findByRole('heading', { level: 1, name: /Where this comes from/ });
    expect(router.state.location.pathname).toBe('/about');
    expect(screen.getByRole('button', { name: 'Menu' }).getAttribute('aria-expanded')).toBe('false');
  });
});

describe('article template', () => {
  it('shows the title block with the question the page answers, above the text', () => {
    renderAt('/how-it-works/differences');
    const header = document.querySelector('.article__header') as HTMLElement;
    expect(within(header).getByRole('heading', { level: 1 })).toBeTruthy();
    expect(within(header).getByText('What does PackSense add that Open Food Facts does not?')).toBeTruthy();
    expect(document.querySelector('.prose h1')).toBeNull();
  });

  it('shows the comparison as a framed table with row headers', () => {
    renderAt('/how-it-works/differences');
    expect(document.querySelectorAll('.table-card')).toHaveLength(1);
    expect(screen.getAllByRole('rowheader')).toHaveLength(8);
  });

  it('puts the barcode button in the header', () => {
    renderAt('/how-it-works/differences');
    const link = within(screen.getByRole('banner')).getByRole('link', { name: 'Look up barcode' });
    expect(link.getAttribute('href')).toBe('/look-up');
  });
});

describe('home', () => {
  it('has the hero, three headline numbers, the Right now strip, five things to do and the aside', () => {
    renderAt('/');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Packaged food data, checked every day.');
    const numbers = screen.getByRole('region', { name: 'Headline numbers' });
    expect(within(numbers).getByText('Products we hold')).toBeTruthy();
    expect(within(numbers).getByText('Edits seen yesterday')).toBeTruthy();
    expect(within(numbers).getByText('Products in the India slice')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'Right now' })).toBeTruthy();
    const list = screen.getByRole('region', { name: 'What you can do on this site' });
    expect(within(list).getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual([
      '/explore/brands',
      '/explore/quality',
      '/explore/changes',
      '/get-the-data',
      '/how-it-works',
    ]);
    expect(screen.getByRole('heading', { level: 2, name: 'What PackSense does not do' })).toBeTruthy();
  });

  it('asks for 8 to 14 digits and announces the problem', () => {
    renderAt('/');
    const input = screen.getByLabelText('Look up a barcode');
    fireEvent.change(input, { target: { value: '12ab' } });
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }));
    expect(screen.getByRole('alert').textContent).toBe('Enter 8 to 14 digits, with no letters.');
    expect(input.getAttribute('aria-invalid')).toBe('true');
  });

  it('takes a valid barcode to the look-up page, kept in the address', async () => {
    const { router } = renderAt('/');
    fireEvent.change(screen.getByLabelText('Look up a barcode'), { target: { value: '8901719135170' } });
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }));
    await screen.findByRole('heading', { level: 1, name: /What does PackSense know about this product/ });
    expect(router.state.location.pathname + router.state.location.search).toBe('/look-up?barcode=8901719135170');
  });

  it('has no accessibility violations that jsdom can detect', async () => {
    const { container } = renderAt('/');
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });
});

// Status values: the 16 Oct 2026 scoreboard of the real site (122,724 products, 24,937 in India), the last complete day of the real change file.
const STATUS_CSV = [
  'built_at_utc,first_complete_day,last_complete_day,products_held_all,products_held_india',
  '2026-10-16T09:01:00,2026-10-01,2026-10-15,122724,24937',
  '',
].join('\n');
const ALL_FILES = {
  'site_status.csv': STATUS_CSV,
  'change_daily.csv': fixture('change_daily.sample.csv'),
  'pipeline_health.csv': fixture('pipeline_health.sample.csv'),
};

describe('home with the published files', () => {
  it('shows the three numbers from the files, with "yesterday" when the last complete day is yesterday', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-16T10:00:00Z'));
    serveFiles(ALL_FILES);
    renderAt('/');
    const numbers = screen.getByRole('region', { name: 'Headline numbers' });
    await waitFor(() => expect(within(numbers).getByText('122,724')).toBeTruthy());
    expect(within(numbers).getByText('24,937')).toBeTruthy();
    expect(within(numbers).getByText('Edits seen yesterday')).toBeTruthy();
    expect(within(numbers).getByText('13')).toBeTruthy();
  });

  it('names the date when the last complete day is older than yesterday, and shows the real arrival times', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-24T10:00:00Z'));
    serveFiles(ALL_FILES);
    renderAt('/');
    const strip = screen.getByRole('region', { name: 'Right now' });
    await waitFor(() => expect(within(strip).getByText('yesterday, 06:31 UTC')).toBeTruthy());
    expect(within(strip).getByText('yesterday, 06:45 UTC')).toBeTruthy();
    expect(within(strip).getByText('15 Oct 2026')).toBeTruthy();
    expect(within(strip).getByText('tomorrow, about 06:45 UTC')).toBeTruthy();
    expect(within(screen.getByRole('region', { name: 'Headline numbers' })).getByText('Edits seen on 15 Oct 2026')).toBeTruthy();
  });

  it('says in words, with a glyph, when daily jobs did not run (the three newest jobs did not exist on 20 Oct)', async () => {
    serveFiles(ALL_FILES);
    renderAt('/');
    const strip = screen.getByRole('region', { name: 'Right now' });
    await waitFor(() => expect(within(strip).getByText(/daily jobs did not run cleanly on 20 Oct 2026/)).toBeTruthy());
  });

  it('shows dashes and one plain notice when the files cannot be loaded, and the rest of the page still works', async () => {
    renderAt('/');
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/could not be loaded just now/));
    expect(within(screen.getByRole('region', { name: 'Headline numbers' })).getAllByText('could not be loaded')).toHaveLength(3);
    expect(screen.getByRole('link', { name: /See which brands fill in/ })).toBeTruthy();
  });

  it('says the files are loading while they are on their way', () => {
    vi.stubGlobal('fetch', () => new Promise(() => {}));
    renderAt('/');
    expect(screen.getByRole('region', { name: 'Headline numbers' }).getAttribute('aria-busy')).toBe('true');
  });
});

const DATA_FILES = { ...ALL_FILES, 'quality_daily.csv': fixture('quality_daily.sample.csv') };

describe('data quality over time', () => {
  it('shows the headline facts, five charts, the kinds of flag and the two text panels, from the real rows', async () => {
    serveFiles(DATA_FILES);
    renderAt('/explore/quality');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Is the data getting better or worse?');
    const headline = await screen.findByRole('region', { name: 'Headline' });
    expect(headline.textContent).toContain('1 Oct 2026 to 15 Oct 2026, 15 whole days');
    expect(within(headline).getAllByText('9.4')).toHaveLength(2);
    expect(within(headline).getByText('233')).toBeTruthy();
    expect(document.querySelectorAll('.chart-card')).toHaveLength(5);
    expect(screen.getByRole('heading', { level: 2, name: 'How to read it' })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'What this page can and cannot tell you' })).toBeTruthy();
  });

  it('names the biggest kind of flag in Open Food Facts words, with its tag and its share, until a plain name is written', async () => {
    serveFiles(DATA_FILES);
    renderAt('/explore/quality');
    const first = (await screen.findAllByRole('rowheader'))[0];
    expect(first.textContent).toContain('Environmental score quality warnings');
    expect(first.textContent).toContain('en:environmental-score-quality-warnings');
    expect(first.closest('tr')?.textContent).toContain('41.0%');
    expect(screen.getByText(/made readable/)).toBeTruthy();
  });

  it('keeps the market in the address and shows the India figures when it is chosen', async () => {
    serveFiles(DATA_FILES);
    const { router } = renderAt('/explore/quality');
    await screen.findByRole('region', { name: 'Headline' });
    const before = screen.getByRole('region', { name: 'Headline' }).textContent;
    fireEvent.click(screen.getByRole('radio', { name: 'India' }));
    await waitFor(() => expect(router.state.location.search).toBe('?market=india'));
    expect(screen.getByRole('radio', { name: 'India' }).getAttribute('aria-checked')).toBe('true');
    expect(screen.getByRole('region', { name: 'Headline' }).textContent).not.toBe(before);
    fireEvent.click(screen.getByRole('radio', { name: 'All markets' }));
    await waitFor(() => expect(router.state.location.search).toBe(''));
  });

  it('opens on India straight from a link that carries the market', async () => {
    serveFiles(DATA_FILES);
    renderAt('/explore/quality?market=india');
    await screen.findByRole('region', { name: 'Headline' });
    expect(screen.getByRole('radio', { name: 'India' }).getAttribute('aria-checked')).toBe('true');
  });

  it('says plainly when the figures could not be loaded, and keeps the text of the page', async () => {
    renderAt('/explore/quality');
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/could not be loaded just now/));
    expect(screen.getByRole('heading', { level: 2, name: 'How to read it' })).toBeTruthy();
  });

  it('has no accessibility violations that jsdom can detect', async () => {
    serveFiles(DATA_FILES);
    const { container } = renderAt('/explore/quality');
    await screen.findByRole('region', { name: 'Headline' });
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });
});

describe('daily changes', () => {
  it('shows the headline figures of the newest day, the busiest day, and the kinds without a total', async () => {
    serveFiles(DATA_FILES);
    renderAt('/explore/changes');
    const headline = await screen.findByRole('region', { name: 'Headline' });
    expect(headline.textContent).toContain('Products edited, 15 Oct 2026 (at least)13');
    expect(headline.textContent).toContain('20, 13 Oct 2026');
    const kinds = screen.getByRole('heading', { level: 2, name: /Work by kind of edit, 15 Oct 2026/ });
    const table = kinds.parentElement?.querySelector('table') as HTMLElement;
    expect(within(table).getAllByRole('rowheader')).toHaveLength(8);
    expect(table.textContent).not.toMatch(/total|sum of/i);
  });

  it('switches between the two chart views and keeps the view in the address', async () => {
    serveFiles(DATA_FILES);
    const { router } = renderAt('/explore/changes');
    await screen.findByRole('region', { name: 'Headline' });
    expect(screen.getByRole('radio', { name: 'Products edited and new' }).getAttribute('aria-checked')).toBe('true');
    expect(screen.getAllByRole('figure')).toHaveLength(1);
    fireEvent.click(screen.getByRole('radio', { name: 'Work by kind' }));
    await waitFor(() => expect(router.state.location.search).toBe('?view=kinds'));
    expect(screen.getAllByRole('figure')).toHaveLength(8);
    expect(screen.getByText(/never added together/)).toBeTruthy();
  });

  it('shows Today in India with its own counts, the days before and a labelled example product', async () => {
    serveFiles(DATA_FILES);
    renderAt('/explore/changes');
    const india = await screen.findByRole('region', { name: 'Today in India' });
    expect(india.textContent).toContain('Newest complete day: 15 Oct 2026');
    expect(india.textContent).toContain('Products edited (at least)8');
    expect(within(india).getByText('parle monaco 700g')).toBeTruthy();
    expect(within(india).getByText(/not necessarily one of today's edits/)).toBeTruthy();
    expect(within(india).getByRole('link', { name: 'See it on Open Food Facts' }).getAttribute('href')).toBe('https://world.openfoodfacts.org/product/8901719135170');
    expect(within(india).getByRole('heading', { level: 2, name: 'What this page can and cannot tell you' })).toBeTruthy();
  });

  it('keeps the India block on India when the main charts show all markets', async () => {
    serveFiles(DATA_FILES);
    renderAt('/explore/changes');
    await screen.findByRole('region', { name: 'Today in India' });
    expect(screen.getByRole('radio', { name: 'All markets' }).getAttribute('aria-checked')).toBe('true');
  });

  it('has no accessibility violations that jsdom can detect', async () => {
    serveFiles(DATA_FILES);
    const { container } = renderAt('/explore/changes');
    await screen.findByRole('region', { name: 'Today in India' });
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });
});

describe('theme button', () => {
  afterEach(() => {
    delete document.documentElement.dataset.theme;
    localStorage.clear();
  });

  it('switches between the light and dark theme, remembers the choice and offers the other one', () => {
    renderAt('/');
    fireEvent.click(screen.getByRole('button', { name: 'Switch to the dark theme' }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem('packsense-theme')).toBe('dark');
    fireEvent.click(screen.getByRole('button', { name: 'Switch to the light theme' }));
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(localStorage.getItem('packsense-theme')).toBe('light');
  });

  it('is in the header on every page', () => {
    renderAt('/how-it-works/differences');
    expect(within(screen.getByRole('banner')).getByRole('button', { name: /Switch to the (dark|light) theme/ })).toBeTruthy();
  });
});

describe('choices on a page', () => {
  it('do not scroll the page to the top or move focus: the market and chart-view switches', async () => {
    serveFiles(DATA_FILES);
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    const { router } = renderAt('/explore/changes');
    await screen.findByRole('region', { name: 'Headline' });
    scrollTo.mockClear();
    focus.mockClear();
    fireEvent.click(screen.getByRole('radio', { name: 'India' }));
    await waitFor(() => expect(router.state.location.search).toBe('?market=india'));
    fireEvent.click(screen.getByRole('radio', { name: 'Work by kind' }));
    await waitFor(() => expect(router.state.location.search).toContain('view=kinds'));
    fireEvent.click(screen.getByRole('radio', { name: 'Products edited and new' }));
    await waitFor(() => expect(router.state.location.search).not.toContain('view='));
    expect(scrollTo).not.toHaveBeenCalled();
    expect(focus).not.toHaveBeenCalledWith({ preventScroll: true });
    scrollTo.mockRestore();
    focus.mockRestore();
  });

  it('do not scroll on the quality page either', async () => {
    serveFiles(DATA_FILES);
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    const { router } = renderAt('/explore/quality');
    await screen.findByRole('region', { name: 'Headline' });
    scrollTo.mockClear();
    fireEvent.click(screen.getByRole('radio', { name: 'India' }));
    await waitFor(() => expect(router.state.location.search).toBe('?market=india'));
    expect(scrollTo).not.toHaveBeenCalled();
    scrollTo.mockRestore();
  });
});

describe('moving between pages', () => {
  it('goes to the very top and does not let focus scroll the page under the sticky header', async () => {
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    renderAt('/');
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'About' }));
    await screen.findByRole('heading', { level: 1, name: /Where this comes from/ });
    expect(scrollTo).toHaveBeenCalledWith(0, 0);
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    scrollTo.mockClear();
    // The same page again (the tab of the page you are on) also goes to the top.
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'About' }));
    await vi.waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 0));
    scrollTo.mockRestore();
    focus.mockRestore();
  });
});

describe('routes', () => {
  it('opens every routed address and shows exactly one h1 on each', () => {
    for (const page of NAV_PAGES) {
      renderAt(page.path);
      expect(screen.getAllByRole('heading', { level: 1 }), page.path).toHaveLength(1);
      cleanup();
    }
  });

  it('shows a plain not-found page for an unknown address', () => {
    renderAt('/nowhere');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('This page does not exist');
  });
});
