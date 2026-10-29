import { copyFileSync, readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vitest/config';
import { parsePage } from './src/content/parse';

const CONTENT_DIR = resolve(__dirname, 'content');
const VIRTUAL = 'virtual:content';

/** Reads the hand-written page texts in content/ at build time and serves them as one module. */
function contentPlugin(): Plugin {
  const resolved = `\0${VIRTUAL}`;
  const loadAll = () =>
    readdirSync(CONTENT_DIR)
      .filter((name) => name.endsWith('.md'))
      .sort()
      .map((name) => parsePage(name, readFileSync(join(CONTENT_DIR, name), 'utf-8')));
  return {
    name: 'packsense-content',
    resolveId: (id) => (id === VIRTUAL ? resolved : null),
    load: (id) => (id === resolved ? `export default ${JSON.stringify(loadAll())};` : null),
    configureServer(server) {
      server.watcher.add(CONTENT_DIR);
      server.watcher.on('change', (file) => {
        if (file.startsWith(CONTENT_DIR)) {
          const mod = server.moduleGraph.getModuleById(resolved);
          if (mod) server.moduleGraph.invalidateModule(mod);
          server.ws.send({ type: 'full-reload' });
        }
      });
    },
  };
}

/** GitHub Pages serves 404.html for an unknown path: a copy of index.html lets the router handle deep links. */
function spaFallbackPlugin(): Plugin {
  let outDir = 'dist';
  return {
    name: 'packsense-spa-fallback',
    apply: 'build',
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      copyFileSync(join(outDir, 'index.html'), join(outDir, '404.html'));
    },
  };
}

export default defineConfig(({ command }) => ({
  base: command === 'build' ? (process.env.APP_BASE ?? '/Packsense/') : '/',
  plugins: [react(), contentPlugin(), spaFallbackPlugin()],
  define: { __BUILD_TIME__: JSON.stringify(new Date().toISOString()) },
  test: { environment: 'jsdom', include: ['src/**/*.test.{ts,tsx}'] },
}));
