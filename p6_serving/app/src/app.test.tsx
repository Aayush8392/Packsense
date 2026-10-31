import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import axe from 'axe-core';
import { createMemoryRouter } from 'react-router';
import { RouterProvider } from 'react-router/dom';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { release } from './data/release';
import { showcase } from './data/showcase';
import { brandScorecard, changeDaily, pipelineHealth, qualityDaily, siteStatus } from './data/siteData';
import { withSpread } from './data/fixtures/withSpread';
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
  for (const resource of [siteStatus, changeDaily, pipelineHealth, qualityDaily, brandScorecard, showcase, release]) resource.reset();
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

const RELEASE_FILES = {
  'release_manifest.json': fixture('release_manifest.fixture.json'),
  'CHANGELOG.md': fixture('release_changelog.fixture.md'),
  'README.md': fixture('release_datacard.fixture.md'),
  'india_sample.csv': fixture('release_sample.fixture.csv'),
};

describe('the India release page', () => {
  it('shows the download card with the real counts, the first rows, and a download link to the public repository', async () => {
    serveFiles(RELEASE_FILES);
    renderAt('/get-the-data');
    const card = await screen.findByRole('region', { name: /India product catalogue, release 2026-10-22/ });
    expect(within(card).getByText('24,932')).toBeTruthy();
    expect(within(card).getByRole('button', { name: 'Download the CSV file' })).toBeTruthy();
    expect(within(card).getByRole('link', { name: 'Data card and all releases on Hugging Face' }).getAttribute('href')).toBe(
      'https://huggingface.co/datasets/PackSense/packsense-india',
    );
    const sample = screen.getByRole('table', { name: 'The first rows of the India file' });
    expect(within(sample).getAllByRole('row')).toHaveLength(11); // ten rows and the header
    expect(within(sample).getByText('00000604')).toBeTruthy(); // the leading zeros are kept
  });

  it('downloads the file with a real save, not a link to the raw text, and falls back to the plain link when the fetch fails', async () => {
    serveFiles(RELEASE_FILES);
    const saved: { name: string; size: number }[] = [];
    const realFetch = globalThis.fetch;
    vi.stubGlobal('fetch', async (url: string, ...rest: unknown[]) =>
      String(url).includes('/resolve/main/india_products.csv') ? new Response(['code,product_name', '00000604,x', ''].join(String.fromCharCode(10)), { status: 200 }) : (realFetch as (u: string, ...r: unknown[]) => Promise<Response>)(url, ...rest));
    URL.createObjectURL = (blob: Blob) => { saved.push({ name: '', size: blob.size }); return 'blob:test'; };
    URL.revokeObjectURL = () => {};
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { saved[saved.length - 1].name = this.download; });
    renderAt('/get-the-data');
    fireEvent.click(await screen.findByRole('button', { name: 'Download the CSV file' }));
    await waitFor(() => expect(screen.getByText('The file was saved to your downloads.')).toBeTruthy());
    expect(saved).toEqual([{ name: 'india_products_2026-10-22.csv', size: 29 }]);
    click.mockRestore();
    cleanup();
    release.reset();
    vi.stubGlobal('fetch', async (url: string, ...rest: unknown[]) =>
      String(url).includes('/resolve/main/india_products.csv') ? new Response('', { status: 500 }) : (realFetch as (u: string, ...r: unknown[]) => Promise<Response>)(url, ...rest));
    renderAt('/get-the-data');
    fireEvent.click(await screen.findByRole('button', { name: 'Download the CSV file' }));
    const fallback = await screen.findByRole('link', { name: 'Open the file in the browser' });
    expect(fallback.getAttribute('href')).toContain('/resolve/main/india_products.csv');
  });

  it('pages the 36 columns ten at a time, with a plain sentence and the share of rows filled', async () => {
    serveFiles(RELEASE_FILES);
    renderAt('/get-the-data');
    const section = (await screen.findByRole('heading', { name: 'The 36 columns, in plain words' })).closest('section') as HTMLElement;
    expect(within(section).getByText('Columns 1 to 10 of 36')).toBeTruthy();
    expect(within(section).getByText('100.0%')).toBeTruthy();
    fireEvent.click(within(section).getByRole('button', { name: 'Next' }));
    expect(within(section).getByText('Columns 11 to 20 of 36')).toBeTruthy();
    expect(within(section).getByText('energy_kj')).toBeTruthy();
  });

  it('copies the credit line, and says so', async () => {
    serveFiles(RELEASE_FILES);
    const written: string[] = [];
    vi.stubGlobal('navigator', { clipboard: { writeText: async (text: string) => { written.push(text); } } });
    renderAt('/get-the-data');
    fireEvent.click(await screen.findByRole('button', { name: 'Copy the credit line' }));
    await waitFor(() => expect(screen.getByText('Copied.')).toBeTruthy());
    expect(written[0]).toContain('Contains data from Open Food Facts');
    expect(written[0]).toContain('release 2026-10-22');
  });

  it('lists the versions with the monthly schedule, and the steps to open the file without breaking barcodes', async () => {
    serveFiles(RELEASE_FILES);
    renderAt('/get-the-data');
    const versions = await screen.findByRole('table', { name: 'Releases of the India file' });
    expect(within(versions).getByText('Latest')).toBeTruthy();
    expect(within(versions).getByText('First release: 24,932 products.')).toBeTruthy();
    expect(screen.getByText(/The 3rd of each month, 10:30 UTC/)).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'How to open the file without breaking barcodes' })).toBeTruthy();
    expect(screen.getByText(/Set “Convert text to numbers, dates and formulas” to No/)).toBeTruthy();
  });

  it('says the first release is not published yet when the manifest is not there, and still shows the steps', async () => {
    serveFiles({});
    renderAt('/get-the-data');
    expect(await screen.findByRole('heading', { name: 'The first release has not been published yet' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Download the CSV file' })).toBeNull();
    expect(screen.getByRole('heading', { name: 'How to open the file without breaking barcodes' })).toBeTruthy();
  });

  it('says the details could not be loaded when a file fails, offers a retry, and still links the repository', async () => {
    vi.stubGlobal('fetch', async () => new Response('', { status: 500 }));
    renderAt('/get-the-data');
    expect(await screen.findByRole('heading', { name: 'The release details could not be loaded just now' })).toBeTruthy();
    expect(screen.getAllByRole('link', { name: 'Data card and all releases on Hugging Face' }).length).toBeGreaterThan(0);
    serveFiles(RELEASE_FILES);
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('region', { name: /India product catalogue, release 2026-10-22/ })).toBeTruthy();
  });
});

const BRAND_FILES = { ...ALL_FILES, 'brand_scorecard.csv': fixture('brand_scorecard.sample.csv') };

describe('how complete the products of a brand are', () => {
  it('has no Details buttons while the published file lacks the eight columns', async () => {
    serveFiles(BRAND_FILES);
    renderAt('/explore/brands');
    await screen.findByRole('region', { name: 'Headline' });
    expect(screen.queryByRole('button', { name: /^Details for / })).toBeNull();
  });

  it('opens a panel of eight bars for one brand, moves focus to it, and closes again', async () => {
    serveFiles({ ...ALL_FILES, 'brand_scorecard.csv': withSpread(fixture('brand_scorecard.sample.csv')) });
    renderAt('/explore/brands');
    await screen.findByRole('region', { name: 'Headline' });
    const open = screen.getAllByRole('button', { name: /^Details for sodebo/ })[0];
    expect(open.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(open);
    const panel = document.getElementById('brand-details') as HTMLElement;
    expect(within(panel).getByRole('heading', { name: 'How complete the products of sodebo are' })).toBe(document.activeElement);
    expect(within(panel).getAllByRole('listitem')).toHaveLength(8);
    expect(open.getAttribute('aria-expanded')).toBe('true');
    expect(panel.textContent).toMatch(/fill all 7 things, and .* fill 5 or more/);
    fireEvent.click(within(panel).getByRole('button', { name: 'Close' }));
    expect(document.getElementById('brand-details')).toBeNull();
    fireEvent.click(open);
    fireEvent.click(open); // pressing the same button again also closes it
    expect(document.getElementById('brand-details')).toBeNull();
  });
});

describe('ordering brands by how complete their products are', () => {
  it('offers the two share orders only with the product groups, and shows the share it orders by', async () => {
    serveFiles(BRAND_FILES);
    renderAt('/explore/brands');
    await screen.findByRole('region', { name: 'Headline' });
    expect(screen.queryByRole('option', { name: /highest share first/ })).toBeNull();
    cleanup();
    brandScorecard.reset();
    serveFiles({ ...ALL_FILES, 'brand_scorecard.csv': withSpread(fixture('brand_scorecard.sample.csv')) });
    renderAt('/explore/brands');
    await screen.findByRole('region', { name: 'Headline' });
    expect(screen.queryByRole('columnheader', { name: 'Fill all 7' })).toBeNull();
    fireEvent.change(screen.getByRole('combobox', { name: 'Order by' }), { target: { value: 'full-share' } });
    expect(screen.getByRole('columnheader', { name: 'Fill all 7' })).toBeTruthy();
    fireEvent.change(screen.getByRole('combobox', { name: 'Order by' }), { target: { value: 'most-share' } });
    expect(screen.getByRole('columnheader', { name: 'Fill 5 or more' })).toBeTruthy();
  });
});

describe('brands', () => {
  const rowsOfTable = () => within(screen.getByRole('table', { name: /share of their products/ })).getAllByRole('row').slice(1);

  it('shows the headline, the histogram, and the best ten brands first, from the real file', async () => {
    serveFiles(BRAND_FILES);
    renderAt('/explore/brands');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Which brands fill in their product information?');
    const headline = await screen.findByRole('region', { name: 'Headline' });
    expect(headline.textContent).toContain('As of 29 Oct 2026');
    expect(within(headline).getByText('583')).toBeTruthy();
    expect(screen.getByText(/583 brands across all markets have 30 or more products/)).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /^Score \d\.\d to \d\.\d: / })).toHaveLength(14);
    const rows = rowsOfTable();
    expect(rows).toHaveLength(10);
    expect(within(rows[0]).getByRole('rowheader').textContent).toBe('sodebo');
    expect(screen.getByText('Brands 1 to 10 of 583')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'What this page can and cannot tell you' })).toBeTruthy();
  });

  it('shows only the brands of a band when its bar is pressed, and all again when it is pressed twice', async () => {
    serveFiles(BRAND_FILES);
    renderAt('/explore/brands');
    await screen.findByRole('region', { name: 'Headline' });
    const bar = screen.getByRole('button', { name: /^Score 6\.5 to 7\.0: 10 brands/ });
    fireEvent.click(bar);
    expect(bar.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('Showing scores 6.5 to 7.0')).toBeTruthy();
    expect(screen.getByText('10 of 583 brands')).toBeTruthy();
    expect(rowsOfTable()).toHaveLength(10);
    fireEvent.click(bar);
    expect(screen.getByText('All 583 brands')).toBeTruthy();
    expect(screen.queryByText(/^Showing scores/)).toBeNull();
  });

  it('finds a brand by name without caring about accents, and says so when nothing matches', async () => {
    serveFiles(BRAND_FILES);
    renderAt('/explore/brands');
    await screen.findByRole('region', { name: 'Headline' });
    fireEvent.change(screen.getByRole('searchbox', { name: 'Find a brand' }), { target: { value: 'NESTLÉ' } });
    const names = rowsOfTable().map((row) => within(row).getByRole('rowheader').textContent);
    expect(names).toContain('nestle');
    fireEvent.change(screen.getByRole('searchbox', { name: 'Find a brand' }), { target: { value: 'zzzz-no-such-brand' } });
    expect(screen.getByText(/No brand matches/)).toBeTruthy();
    expect(screen.queryByRole('table', { name: /share of their products/ })).toBeNull();
  });

  it('pages the table ten brands at a time and goes back to the first page when the order changes', async () => {
    serveFiles(BRAND_FILES);
    renderAt('/explore/brands');
    await screen.findByRole('region', { name: 'Headline' });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText('Brands 11 to 20 of 583')).toBeTruthy();
    fireEvent.change(screen.getByRole('combobox', { name: 'Order by' }), { target: { value: 'name' } });
    expect(screen.getByText('Brands 1 to 10 of 583')).toBeTruthy();
    const names = rowsOfTable().map((row) => within(row).getByRole('rowheader').textContent ?? '');
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
  });

  it('switches to the India brands and clears the band when the market changes, without moving the page', async () => {
    serveFiles(BRAND_FILES);
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    const { router } = renderAt('/explore/brands');
    await screen.findByRole('region', { name: 'Headline' });
    fireEvent.click(screen.getByRole('button', { name: /^Score 6\.5 to 7\.0/ }));
    scrollTo.mockClear();
    fireEvent.click(screen.getByRole('radio', { name: 'India' }));
    await waitFor(() => expect(router.state.location.search).toBe('?market=india'));
    expect(screen.getByText(/87 brands in India have 30 or more products/)).toBeTruthy();
    expect(screen.getByText('All 87 brands')).toBeTruthy();
    expect(scrollTo).not.toHaveBeenCalled();
    scrollTo.mockRestore();
  });

  it('gives the same numbers as a table behind the histogram', async () => {
    serveFiles(BRAND_FILES);
    renderAt('/explore/brands');
    await screen.findByRole('region', { name: 'Headline' });
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    const table = screen.getByRole('table', { name: 'Brands in each score band' });
    expect(within(table).getAllByRole('row')).toHaveLength(15);
    expect(within(within(table).getByRole('rowheader', { name: '3.5 to 4.0' }).closest('tr') as HTMLElement).getByText('82')).toBeTruthy();
  });

  it('says plainly when the file could not be loaded, and keeps the text of the page', async () => {
    renderAt('/explore/brands');
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/could not be loaded just now/));
    expect(screen.getByRole('heading', { level: 2, name: 'What this page can and cannot tell you' })).toBeTruthy();
  });

  it('has no accessibility violations that jsdom can detect', async () => {
    serveFiles(BRAND_FILES);
    const { container } = renderAt('/explore/brands');
    await screen.findByRole('region', { name: 'Headline' });
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });
});

const HEALTH_FILES = { ...DATA_FILES, 'pipeline_health.csv': fixture('pipeline_health.real.csv') };

describe('pipeline health', () => {
  const jobRows = () => within(screen.getByRole('table', { name: /scheduled jobs/ })).getAllByRole('row').slice(1);

  it('shows the headline of the newest check, a row for each of the twelve jobs, and the key to the verdict words', async () => {
    serveFiles(HEALTH_FILES);
    renderAt('/how-it-works/health');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Is the system running right now?');
    const headline = await screen.findByRole('region', { name: 'Headline' });
    expect(headline.textContent).toContain('Checked once a day. Every day, 08:40 UTC. Newest check: 30 Oct 2026');
    expect(within(headline).getByText('8 of 12')).toBeTruthy();
    expect(within(headline).getByText('4')).toBeTruthy();
    expect(within(headline).getByText('7 of 7')).toBeTruthy();
    expect(jobRows()).toHaveLength(12);
    const key = document.querySelector('.verdict-key') as HTMLElement;
    expect(within(key).getAllByText(/On time|Late|Missed|Not known/)).toHaveLength(4);
  });

  it('judges a weekly job by its own week: the snapshot job is on time and the weekly load is late', async () => {
    serveFiles(HEALTH_FILES);
    renderAt('/how-it-works/health');
    await screen.findByRole('region', { name: 'Headline' });
    const row = (name: string) => jobRows().find((r) => within(r).getByRole('rowheader').textContent === name) as HTMLElement;
    expect(row('snapshots').textContent).toContain('Mondays, 12:00 UTC');
    expect(row('snapshots').textContent).toContain('On time');
    expect(row('reconcile-load').textContent).toContain('Late');
    expect(row('publish').textContent).toContain('Missed');
    expect(row('snapshots').textContent).toContain('14 of 21');
  });

  it('says in plain words what each job and each outside service is for', async () => {
    serveFiles(HEALTH_FILES);
    renderAt('/how-it-works/health');
    await screen.findByRole('region', { name: 'Headline' });
    const jobs = within(screen.getByRole('table', { name: /scheduled jobs/ }));
    expect(jobs.getByRole('columnheader', { name: 'What it is for' })).toBeTruthy();
    expect(jobs.getAllByRole('row').slice(1).every((r) => (r.querySelector('td')?.textContent ?? '').length > 20)).toBe(true);
    const services = within(screen.getByRole('table', { name: /outside services/ }));
    expect(services.getByRole('columnheader', { name: 'What it is for' })).toBeTruthy();
    expect(services.getAllByRole('row').slice(1).every((r) => (r.querySelector('td')?.textContent ?? '').length > 20)).toBe(true);
  });

  it('draws the run times and the products held, and gives the services with the expected refusal marked', async () => {
    serveFiles(HEALTH_FILES);
    renderAt('/how-it-works/health');
    await screen.findByRole('region', { name: 'Headline' });
    expect(document.querySelectorAll('.chart-card')).toHaveLength(2);
    const services = within(screen.getByRole('table', { name: /outside services/ })).getAllByRole('row').slice(1);
    expect(services).toHaveLength(7);
    const b2 = services.find((r) => r.textContent?.includes('Backblaze')) as HTMLElement;
    expect(b2.textContent).toContain('HTTP 403');
    expect(b2.textContent).toContain('Expected');
    expect(services.filter((r) => r.textContent?.includes('Expected'))).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 2, name: 'What this page can and cannot tell you' })).toBeTruthy();
  });

  it('says plainly when the file could not be loaded, and keeps the text of the page', async () => {
    renderAt('/how-it-works/health');
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/could not be loaded just now/));
    expect(screen.getByRole('heading', { level: 2, name: 'What this page can and cannot tell you' })).toBeTruthy();
  });

  it('has no accessibility violations that jsdom can detect', async () => {
    serveFiles(HEALTH_FILES);
    const { container } = renderAt('/how-it-works/health');
    await screen.findByRole('region', { name: 'Headline' });
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });
});

const SHOWCASE_FILES = { ...ALL_FILES, 'showcase.json': readFileSync(join(import.meta.dirname, '..', '..', 'showcase', 'showcase.json'), 'utf-8') };

describe('how PackSense works', () => {
  const lists = () => ({
    raw: document.querySelector('section[aria-labelledby="raw-title"]') as HTMLElement,
    silver: document.querySelector('section[aria-labelledby="silver-title"]') as HTMLElement,
  });

  it('shows the three steps with the real counts of the first product, and a switcher for the four products', async () => {
    serveFiles(SHOWCASE_FILES);
    renderAt('/how-it-works');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('From a raw file to a table you can read.');
    const flow = await screen.findByRole('list', { name: 'The three steps' });
    expect(flow.textContent).toContain('245 fields, exactly as they arrived.');
    expect(flow.textContent).toContain('81 columns, 17 of them hidden on purpose.');
    expect(flow.textContent).toContain('8 tables');
    const group = screen.getByRole('radiogroup', { name: 'Product to follow' });
    expect(within(group).getAllByRole('radio')).toHaveLength(4);
    expect(within(group).getByRole('radio', { name: /Kinder Surprise/ }).getAttribute('aria-checked')).toBe('true');
    expect(screen.getByText(/barcode 8000500026731, brand Ferrero, Kinder/)).toBeTruthy();
  });

  it('shows the same four facts at each step, from real values', async () => {
    serveFiles(SHOWCASE_FILES);
    renderAt('/how-it-works');
    const table = await screen.findByRole('table', { name: /Name, pack size, categories and energy of Kinder Surprise/ });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((r) => within(r).getByRole('rowheader').textContent)).toEqual(['Name', 'Pack size', 'Categories', 'Energy per 100 g']);
    expect(rows[3].textContent).toContain('energy-kcal "561" in the packaging set per 100g; the record holds 3 separate sets');
  });

  it('lists the raw fields ten at a time, searches them, and says how many there are', async () => {
    serveFiles(SHOWCASE_FILES);
    renderAt('/how-it-works');
    await screen.findByRole('list', { name: 'The three steps' });
    const { raw } = lists();
    expect(within(raw).getByText('All 245 fields')).toBeTruthy();
    expect(raw.querySelectorAll('.kv__row')).toHaveLength(10);
    expect(within(raw).getByText('Fields 1 to 10 of 245')).toBeTruthy();
    fireEvent.change(within(raw).getByRole('searchbox', { name: 'Search the fields' }), { target: { value: 'PRODUCT_NAME' } });
    expect(raw.querySelectorAll('.kv__row').length).toBeGreaterThan(0);
    expect([...raw.querySelectorAll('.kv__row')].every((row) => (row.textContent ?? '').toLowerCase().includes('product_name'))).toBe(true);
    expect(within(raw).getByText(/of 245 fields/)).toBeTruthy();
    fireEvent.change(within(raw).getByRole('searchbox', { name: 'Search the fields' }), { target: { value: 'zzzz-nothing' } });
    expect(within(raw).getByText('Nothing matches. Try another word.')).toBeTruthy();
  });

  it('cuts the cleaned row to the 17 hidden columns and marks each one "hidden on purpose"', async () => {
    serveFiles(SHOWCASE_FILES);
    renderAt('/how-it-works');
    await screen.findByRole('list', { name: 'The three steps' });
    const { silver } = lists();
    expect(within(silver).getByText('All 81 columns')).toBeTruthy();
    fireEvent.click(within(silver).getByRole('radio', { name: 'Hidden on purpose' }));
    expect(within(silver).getByText('17 of 81 columns')).toBeTruthy();
    expect(silver.querySelectorAll('.kv__row--hidden')).toHaveLength(10);
    expect(within(silver).getAllByText('hidden on purpose')).toHaveLength(10);
    fireEvent.click(within(silver).getByRole('button', { name: 'Next' }));
    expect(within(silver).getByText('Columns 11 to 17 of 17')).toBeTruthy();
    fireEvent.click(within(silver).getByRole('radio', { name: 'Kept' }));
    expect(within(silver).getByText('64 of 81 columns')).toBeTruthy();
  });

  it('shows the eight gold tables with their real rows, and the signal words on the product card', async () => {
    serveFiles(SHOWCASE_FILES);
    renderAt('/how-it-works');
    await screen.findByRole('list', { name: 'The three steps' });
    expect(document.querySelectorAll('.gold-card')).toHaveLength(8);
    const card = document.querySelector('section[aria-labelledby="gold-mart_product_card"]') as HTMLElement;
    expect(within(card).getByText('Nothing flagged.')).toBeTruthy();
    const flags = screen.getByRole('table', { name: /Flags it carried for Kinder Surprise/ });
    expect(within(flags).getAllByRole('row')).toHaveLength(8); // seven flags and the header
  });

  it('keeps the 11 arithmetic checks together on one page, even for a product with 22 rows', async () => {
    serveFiles(SHOWCASE_FILES);
    renderAt('/how-it-works?product=long_history');
    await screen.findByText(/A long edit history: 18 versions kept\./);
    const checks = screen.getByRole('table', { name: /The arithmetic checks for/ });
    expect(within(checks).getAllByRole('row')).toHaveLength(12); // eleven checks and the header
    cleanup();
    renderAt('/how-it-works');
    await screen.findByRole('list', { name: 'The three steps' });
    const kinder = screen.getByRole('table', { name: /The arithmetic checks for/ });
    expect(within(kinder).getAllByRole('row')).toHaveLength(12);
    expect(within(kinder.closest('section') as HTMLElement).queryByRole('button', { name: 'Next' })).toBeNull();
  });

  it('switches to another product from the switcher or from a link, and keeps the choice in the address', async () => {
    serveFiles(SHOWCASE_FILES);
    const { router } = renderAt('/how-it-works');
    await screen.findByRole('list', { name: 'The three steps' });
    fireEvent.click(screen.getByRole('radio', { name: /parle monaco/ }));
    await waitFor(() => expect(router.state.location.search).toBe('?product=india'));
    expect(screen.getByRole('table', { name: /Name, pack size, categories and energy of parle monaco 700g/ })).toBeTruthy();
    expect(screen.getByText(/A product from India\./)).toBeTruthy();
    expect(screen.getByRole('list', { name: 'The three steps' }).textContent).toContain('178 fields');
    cleanup();
    renderAt('/how-it-works?product=long_history');
    expect(await screen.findByText(/A long edit history: 18 versions kept\./)).toBeTruthy();
    const history = screen.getByRole('table', { name: /Version history for Chocolate Reduced Fat Ultra-filtered Milk/ });
    expect(within(history).getAllByRole('row')).toHaveLength(11); // ten rows a page and the header
  });

  it('lists what was removed or replaced, with the real counts', async () => {
    serveFiles(SHOWCASE_FILES);
    renderAt('/how-it-works');
    const heading = await screen.findByRole('heading', { level: 2, name: 'What was removed or replaced before showing it' });
    const section = heading.closest('section') as HTMLElement;
    expect(section.textContent).toContain('102 fields that name volunteers');
    expect(section.textContent).toContain('contributor-A, contributor-B, contributor-C');
  });

  it('says plainly when the file could not be loaded, and keeps the text of the page', async () => {
    renderAt('/how-it-works');
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/could not be loaded just now/));
    expect(screen.getByRole('heading', { level: 2, name: 'What this page can and cannot tell you' })).toBeTruthy();
    expect(screen.getByText(/From a raw file/)).toBeTruthy();
  });

  it('has no accessibility violations that jsdom can detect', async () => {
    serveFiles(SHOWCASE_FILES);
    const { container } = renderAt('/how-it-works');
    await screen.findByRole('list', { name: 'The three steps' });
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
