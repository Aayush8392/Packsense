import { useCallback, useState } from 'react';
import { useLocation } from 'react-router';

const PREFIX = 'packsense-state:';

/** Forgets one saved choice (a jump to a page opens it fresh). */
export function forgetState(pathname: string, name: string): void {
  try {
    sessionStorage.removeItem(`${PREFIX}${pathname}:${name}`);
  } catch {
    // Nothing to forget when storage is blocked.
  }
}

/**
 * A choice the visitor makes on a page (a search, an order, a page of a table, the row that is open), kept for this tab: it survives a refresh and coming Back to the
 * page, and it is forgotten by a fresh view (the menu). `initial` is used when nothing is saved or the saved value is not readable.
 */
export function usePageState<T>(name: string, initial: T): [T, (next: T) => void] {
  const { pathname } = useLocation();
  const key = `${PREFIX}${pathname}:${name}`;
  const [value, setValue] = useState<T>(() => {
    try {
      const saved = sessionStorage.getItem(key);
      return saved === null ? initial : (JSON.parse(saved) as T);
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (next: T) => {
      setValue(next);
      try {
        sessionStorage.setItem(key, JSON.stringify(next));
      } catch {
        // Storage can be blocked; the choice then lasts until the page is closed.
      }
    },
    [key],
  );
  return [value, set];
}
