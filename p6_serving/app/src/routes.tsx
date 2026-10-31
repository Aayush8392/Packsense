import type { RouteObject } from 'react-router';
import { Shell } from './components/Shell';
import { NAV_PAGES } from './nav';
import { Article } from './pages/Article';
import { BrandsPage } from './pages/BrandsPage';
import { DailyChangesPage } from './pages/DailyChangesPage';
import { HowItWorksPage } from './pages/HowItWorksPage';
import { Home } from './pages/Home';
import { NotFound } from './pages/NotFound';
import { PipelineHealthPage } from './pages/PipelineHealthPage';
import { QualityPage } from './pages/QualityPage';
import { ReleasePage } from './pages/ReleasePage';

/** Pages with their own layout; every other page is its text in the article frame. */
function elementFor(slug: string) {
  if (slug === 'home') return <Home />;
  if (slug === 'brands') return <BrandsPage />;
  if (slug === 'how-we-work') return <HowItWorksPage />;
  if (slug === 'pipeline-health') return <PipelineHealthPage />;
  if (slug === 'quality-over-time') return <QualityPage />;
  if (slug === 'daily-changes') return <DailyChangesPage />;
  if (slug === 'india-release') return <ReleasePage />;
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
