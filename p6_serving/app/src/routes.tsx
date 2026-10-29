import type { RouteObject } from 'react-router';
import { Shell } from './components/Shell';
import { NAV_PAGES } from './nav';
import { Article } from './pages/Article';
import { DailyChangesPage } from './pages/DailyChangesPage';
import { Home } from './pages/Home';
import { NotFound } from './pages/NotFound';
import { QualityPage } from './pages/QualityPage';

/** Pages with their own layout; every other page is its text in the article frame. */
function elementFor(slug: string) {
  if (slug === 'home') return <Home />;
  if (slug === 'quality-over-time') return <QualityPage />;
  if (slug === 'daily-changes') return <DailyChangesPage />;
  return <Article slug={slug} />;
}

export const routes: RouteObject[] = [
  {
    element: <Shell />,
    children: [
      ...NAV_PAGES.map((page) => ({
        path: page.path,
        element: elementFor(page.slug),
      })),
      { path: '*', element: <NotFound /> },
    ],
  },
];
