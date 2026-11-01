import { useSyncExternalStore } from 'react';
import { resetConversation } from './chatStore';

/**
 * Whether the question button is on the page, and whether its panel is open. The visitor decides: it starts hidden, the "Ask" button in the header (or the line on the home
 * page) shows it, and the choice is kept in the browser (a blocked or private window just forgets it when the page is closed).
 */
const KEY = 'packsense-chat';

export interface ChatState {
  visible: boolean;
  open: boolean;
}

function storedVisible(): boolean {
  try {
    return localStorage.getItem(KEY) === 'on';
  } catch {
    return false;
  }
}

function remember(visible: boolean) {
  try {
    localStorage.setItem(KEY, visible ? 'on' : 'off');
  } catch {
    // Storage can be blocked; the choice then lasts until the page is closed.
  }
}

let state: ChatState = { visible: storedVisible(), open: false };
const listeners = new Set<() => void>();

function set(next: ChatState) {
  state = next;
  listeners.forEach((listener) => listener());
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export const getChat = (): ChatState => state;

export function useChat(): ChatState {
  return useSyncExternalStore(subscribe, () => state);
}

/** Puts the button on the page (and opens the panel when asked to, as the home page line does). */
export function showChat(open = false): void {
  remember(true);
  set({ visible: true, open });
}

/** Takes the button, and the panel with it, off the page. */
export function hideChat(): void {
  remember(false);
  set({ visible: false, open: false });
}

export function toggleChatVisible(): void {
  if (state.visible) hideChat();
  else showChat();
}

export function setChatOpen(open: boolean): void {
  if (state.visible) set({ ...state, open });
}

/** For tests: back to the starting state (hidden), or visible, without touching the browser's storage. */
export function resetChat(visible = false): void {
  resetConversation();
  set({ visible, open: false });
}
