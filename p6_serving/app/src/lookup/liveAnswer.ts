import { RELEASE_REPO, loadRelease } from '../data/release';
import { fetchText, parseSiteStatus } from '../data/siteData';
import { formatCount } from '../format';

/** What an answer shows when the figure it needs is not published on the site (yet). */
export const NOT_PUBLISHED = 'The live figure this answer needs is not published on this site yet.';
export const NOT_LOADED = 'The live figure this answer needs could not be loaded just now.';

type Value = () => Promise<string>;

/**
 * The figures an answer can carry as {name}, filled from the files the site already publishes. Only figures with one clear meaning are here; the rest of the
 * catalogue's data answers wait until their figure is published, and say so instead of showing the placeholder.
 */
const FILLERS: Record<string, Value> = {
  products_held: async () => formatCount(parseSiteStatus(await fetchText('site_status.csv')).productsAll),
  india_products: async () => formatCount(parseSiteStatus(await fetchText('site_status.csv')).productsIndia),
  release_rows: async () => {
    const state = await loadRelease();
    if (!state.published) throw new Error('no release');
    return formatCount(state.release.products);
  },
  release_link: async () => RELEASE_REPO,
};

/** The answer with its {figures} filled in, or a plain notice when one of them cannot be. */
export async function fillAnswer(text: string): Promise<string> {
  const names = [...new Set([...text.matchAll(/\{([a-z_]+)\}/g)].map((m) => m[1]))];
  if (names.length === 0) return text;
  if (names.some((name) => !(name in FILLERS))) return NOT_PUBLISHED;
  try {
    const values = await Promise.all(names.map((name) => FILLERS[name]()));
    return names.reduce((out, name, i) => out.split(`{${name}}`).join(values[i]), text);
  } catch {
    return NOT_LOADED;
  }
}
