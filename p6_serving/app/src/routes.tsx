import type { RouteObject } from 'react-router';
import { Shell } from './components/Shell';
import { NAV_PAGES } from './nav';
import { Article } from './pages/Article';
import { Home } from './pages/Home';
import { NotFound } from './pages/NotFound';

export const routes: RouteObject[] = [
  {
    element: <Shell />,
    children: [
      ...NAV_PAGES.map((page) => ({
        path: page.path,
        element: page.slug === 'home' ? <Home /> : <Article slug={page.slug} />,
      })),
      { path: '*', element: <NotFound /> },
    ],
  },
];
