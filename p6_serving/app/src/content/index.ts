import pages from 'virtual:content';
import type { Page } from './parse';

export const PAGES: Page[] = pages as Page[];

export function pageBySlug(slug: string): Page | undefined {
  return PAGES.find((page) => page.meta.slug === slug);
}
