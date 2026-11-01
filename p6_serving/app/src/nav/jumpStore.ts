import { useSyncExternalStore } from 'react';

/**
 * The trail of jumps. A jump is a click that opens another page on purpose, with the thing you clicked in focus (see JumpLink). Each jump leaves a step behind:
 * the address of the page you left (with its choices), how far you had scrolled, and its name. The floating Back button takes the newest step off the trail and
 * returns to it. The trail belongs to the open tab (session storage): a refresh keeps it, closing the tab ends it.
 */
export interface Step {
  /** The page left, as pathname + search, without the app's base path. */
  path: string;
  scroll: number;
  /** Where the visitor was, in words ("Home"), for the button. */
  label: string;
}

const KEY = 'packsense-jumps';
const STATE_PREFIX = 'packsense-state:';

function read(): Step[] {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(KEY) ?? '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((step): step is Step => typeof step?.path === 'string' && typeof step?.scroll === 'number' && typeof step?.label === 'string');
  } catch {
    return [];
  }
}

function write(steps: Step[]) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(steps));
  } catch {
    // Storage can be blocked; the trail then lasts until the page is refreshed.
  }
}

let trail: Step[] = read();
const listeners = new Set<() => void>();

function set(next: Step[]) {
  trail = next;
  write(next);
  listeners.forEach((listener) => listener());
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export const getTrail = (): Step[] => trail;

export function useTrail(): Step[] {
  return useSyncExternalStore(subscribe, () => trail);
}

/** A jump leaves this step behind. */
export function pushStep(step: Step): void {
  set([...trail, step]);
}

/** Takes the newest step off the trail and hands it back (undefined when the trail is empty). */
export function popStep(): Step | undefined {
  const step = trail[trail.length - 1];
  if (step) set(trail.slice(0, -1));
  return step;
}

/** A jump opens its destination fresh: whatever that page had saved from an earlier visit is forgotten. */
export function forgetPage(pathname: string): void {
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const key = sessionStorage.key(i);
      if (key?.startsWith(`${STATE_PREFIX}${pathname}:`)) sessionStorage.removeItem(key);
    }
  } catch {
    // Nothing to forget when storage is blocked.
  }
}

function forgetPageChoices() {
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const key = sessionStorage.key(i);
      if (key?.startsWith(STATE_PREFIX)) sessionStorage.removeItem(key);
    }
  } catch {
    // Nothing to forget when storage is blocked.
  }
}

/** The menu, the logo and the page links start a fresh view: no trail, and every page's saved choices are forgotten. */
export function startFreshView(): void {
  forgetPageChoices();
  if (trail.length > 0) set([]);
}

/** For tests: an empty trail and no saved choices. */
export function resetTrail(): void {
  forgetPageChoices();
  set([]);
}
