export type TabId = 'home' | 'explore' | 'how' | 'data' | 'lookup' | 'about';

export interface Tab {
  id: TabId;
  label: string;
  /** Where the tab's link goes. */
  path: string;
}

export interface NavPage {
  slug: string;
  path: string;
  tab: TabId;
  /** Short name for the second-level row and the breadcrumb. */
  label: string;
}

export const TABS: Tab[] = [
  { id: 'home', label: 'Home', path: '/' },
  { id: 'explore', label: 'Explore the data', path: '/explore/brands' },
  { id: 'how', label: 'How it works', path: '/how-it-works' },
  { id: 'data', label: 'Get the data', path: '/get-the-data' },
  { id: 'lookup', label: 'Look up', path: '/look-up' },
  { id: 'about', label: 'About', path: '/about' },
];

/** Every routed page, in menu order. `slug` is the slug in the page's front matter. */
export const NAV_PAGES: NavPage[] = [
  { slug: 'home', path: '/', tab: 'home', label: 'Home' },
  { slug: 'brands', path: '/explore/brands', tab: 'explore', label: 'Brands' },
  { slug: 'quality-over-time', path: '/explore/quality', tab: 'explore', label: 'Data quality over time' },
  { slug: 'daily-changes', path: '/explore/changes', tab: 'explore', label: 'Daily changes' },
  { slug: 'how-we-work', path: '/how-it-works', tab: 'how', label: 'How PackSense works' },
  { slug: 'how-we-differ', path: '/how-it-works/differences', tab: 'how', label: 'How PackSense differs' },
  { slug: 'pipeline-health', path: '/how-it-works/health', tab: 'how', label: 'Pipeline health' },
  { slug: 'india-release', path: '/get-the-data', tab: 'data', label: 'The India release' },
  { slug: 'barcode-lookup', path: '/look-up', tab: 'lookup', label: 'Barcode lookup' },
  { slug: 'about', path: '/about', tab: 'about', label: 'About' },
];

/**
 * Pages whose text is not routed on its own: 'India today' (06) becomes a block inside Daily changes and 'Ask a question' (11) a panel
 * inside Look up. Their files stay in content/ until those pages are built (slices 3 and 6).
 */
export const FOLDED_SLUGS = ['india-today', 'ask-a-question'];

export function pageForPath(pathname: string): NavPage | undefined {
  const clean = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  return NAV_PAGES.find((page) => page.path === clean);
}

export function tabById(id: TabId): Tab {
  return TABS.find((tab) => tab.id === id) as Tab;
}

export function pagesInTab(id: TabId): NavPage[] {
  return NAV_PAGES.filter((page) => page.tab === id);
}
