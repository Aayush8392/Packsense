import '@fontsource/newsreader/500.css';
import '@fontsource/newsreader/600.css';
import '@fontsource/public-sans/400.css';
import '@fontsource/public-sans/600.css';
import './tokens.css';
import './base.css';
import './dataPages.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter } from 'react-router';
import { RouterProvider } from 'react-router/dom';
import { startBot } from './lookup/botStore';
import { routes } from './routes';

const router = createBrowserRouter(routes, { basename: import.meta.env.BASE_URL.replace(/\/$/, '') || '/' });

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);

// The question tool downloads in the background from the first page on (chunks, at an idle moment, skipped on Data Saver or a slow connection).
startBot();
