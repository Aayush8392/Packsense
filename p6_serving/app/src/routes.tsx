import { lazy, Suspense } from 'react';
import type { RouteObject } from 'react-router';
import { Shell } from './components/Shell';
import { NAV_PAGES } from './nav';
import { Home } from './pages/Home';
import { NotFound } from './pages/NotFound';

/** Each page is its own file, fetched when its address is opened (Home, the shell and the 404 page stay in the main file). */
const Article = lazy(() => import('./pages/Article').then((m) => ({ default: m.Article })));
const BrandsPage = lazy(() => import('./pages/BrandsPage').then((m) => ({ default: m.BrandsPage })));
const DailyChangesPage = lazy(() => import('./pages/DailyChangesPage').then((m) => ({ default: m.DailyChangesPage })));
const HowItWorksPage = lazy(() => import('./pages/HowItWorksPage').then((m) => ({ default: m.HowItWorksPage })));
const LookUpPage = lazy(() => import('./pages/LookUpPage').then((m) => ({ default: m.LookUpPage })));
const PipelineHealthPage = lazy(() => import('./pages/PipelineHealthPage').then((m) => ({ default: m.PipelineHealthPage })));
const QualityPage = lazy(() => import('./pages/QualityPage').then((m) => ({ default: m.QualityPage })));
const ReleasePage = lazy(() => import('./pages/ReleasePage').then((m) => ({ default: m.ReleasePage })));

/** Pages with their own layout; every other page is its text in the article frame. */
function elementFor(slug: string) {
  if (slug === 'home') return <Home />;
  if (slug === 'brands') return <BrandsPage />;
  if (slug === 'how-we-work') return <HowItWorksPage />;
  if (slug === 'pipeline-health') return <PipelineHealthPage />;
  if (slug === 'quality-over-time') return <QualityPage />;
  if (slug === 'daily-changes') return <DailyChangesPage />;
  if (slug === 'india-release') return <ReleasePage />;
  if (slug === 'barcode-lookup') return <LookUpPage />;
  return <Article slug={slug} />;
}

export const routes: RouteObject[] = [
  {
    element: <Shell />,
    children: [
      ...NAV_PAGES.map((page) => ({
        path: page.path,
        element: <Suspense fallback={<p role="status">Loading the page…</p>}>{elementFor(page.slug)}</Suspense>,
      })),
      { path: '*', element: <NotFound /> },
    ],
  },
];
