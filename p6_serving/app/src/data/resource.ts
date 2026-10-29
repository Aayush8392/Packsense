import { useEffect, useSyncExternalStore } from 'react';

export type Loaded<T> =
  | { phase: 'idle' | 'loading' }
  | { phase: 'ready'; data: T }
  | { phase: 'error'; error: string };

export interface Resource<T> {
  subscribe(listener: () => void): () => void;
  getSnapshot(): Loaded<T>;
  /** Starts loading the first time it is called; later calls do nothing, so a page visited again does not fetch again. */
  start(): void;
  /** Forgets what was loaded (used by tests and by a retry button). */
  reset(): void;
}

const IDLE: Loaded<never> = { phase: 'idle' };

/** One file loaded once and shared by every page that shows it. */
export function createResource<T>(load: () => Promise<T>): Resource<T> {
  let state: Loaded<T> = IDLE;
  const listeners = new Set<() => void>();
  const set = (next: Loaded<T>) => {
    state = next;
    listeners.forEach((listener) => listener());
  };
  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => state,
    start() {
      if (state.phase !== 'idle') return;
      set({ phase: 'loading' });
      load().then(
        (data) => set({ phase: 'ready', data }),
        (error: unknown) => set({ phase: 'error', error: error instanceof Error ? error.message : String(error) }),
      );
    },
    reset() {
      set(IDLE);
    },
  };
}

export function useResource<T>(resource: Resource<T>): Loaded<T> {
  useEffect(() => resource.start(), [resource]);
  return useSyncExternalStore(resource.subscribe, resource.getSnapshot);
}
