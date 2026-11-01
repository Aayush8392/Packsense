import { useSyncExternalStore } from 'react';
import { fillAnswer } from './liveAnswer';

/**
 * What the question tool shows for a question, ready to display. `remember` is the entry the conversation settled on (the answer shown, or the nearest question when only
 * suggestions were offered): the chat hands it back with the next question, so a short follow-up ("and in India?") can lean on it.
 */
export type BotAnswer = { remember: string | null } & (
  | { kind: 'answer'; parts: { question: string; answer: string }[]; combined: boolean }
  /** No answer the bot is sure of: the nearest questions, each with its own ready answer; `close` says the nearest is close to what was asked. */
  | { kind: 'suggestions'; items: { id: string; question: string }[]; close: boolean }
  | { kind: 'reply'; text: string }
);

export interface BotApi {
  ask(text: string, prevId?: string | null): Promise<BotAnswer>;
  /** The answer to one of the suggested questions: exactly that entry's answer, so the visitor is sure to get an answer to the question they picked. */
  answerEntry(id: string): Promise<BotAnswer>;
}

export type BotState =
  | { phase: 'idle' }
  /** The visitor asked for less data (Data Saver) or the connection is slow, so nothing was downloaded. */
  | { phase: 'skipped' }
  | { phase: 'loading'; done: number; total: number }
  | { phase: 'ready'; api: BotApi }
  | { phase: 'error' };

const IDLE: BotState = { phase: 'idle' };
let state: BotState = IDLE;
/** True from the moment a start was accepted until it has settled, so a second call in between cannot start a second download. */
let starting = false;
const listeners = new Set<() => void>();

function set(next: BotState) {
  state = next;
  listeners.forEach((listener) => listener());
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** The state now, for code outside React (and for tests). */
export const getBotState = (): BotState => state;

export function useBot(): BotState {
  return useSyncExternalStore(subscribe, () => state);
}

/** Where the bot's chunk files are served from: the app's own `data/bot/` folder. */
export const botBase = () => `${import.meta.env.BASE_URL}data/bot/`;

/** Loads the files and builds the bot. The bot's code is fetched here, on demand, so it is not part of the first page. */
export async function loadBotApi(base: string, onProgress: (done: number, total: number) => void = () => {}): Promise<BotApi> {
  const [{ loadBundle }, { createShrunkBot }] = await Promise.all([import('../../../bot/port/shrunk_loader.mjs'), import('../../../bot/port/shrunk_bot.mjs')]);
  const bot = createShrunkBot(await loadBundle({ base, onProgress }));
  const fromEntries = async (ids: string[], combined: boolean, remember: string | null): Promise<BotAnswer> => ({
    kind: 'answer',
    parts: await Promise.all(ids.map(async (id) => {
      const { question, answer } = bot.entry(id);
      return { question, answer: await fillAnswer(answer) };
    })),
    combined,
    remember,
  });
  return {
    async ask(text, prevId = null) {
      const { shown, remember } = await bot.ask(text, prevId);
      if (shown.kind === 'answer') return fromEntries(shown.entries, shown.combined, remember);
      if (shown.kind === 'suggestions') return { kind: 'suggestions', close: shown.close, items: shown.entries.map((id) => ({ id, question: bot.entry(id).question })), remember };
      return { kind: 'reply', text: shown.text, remember };
    },
    async answerEntry(id) {
      return fromEntries([id], false, id);
    },
  };
}

/**
 * Starts the download once, when the app opens: at an idle moment, and not at all when the visitor asked for less data or the connection is slow (they can ask for it
 * on the page). Later calls do nothing unless the first one failed or was skipped and `force` is set.
 */
export function startBot({ force = false, load = loadBotApi }: { force?: boolean; load?: typeof loadBotApi } = {}): void {
  if (starting || state.phase === 'loading' || state.phase === 'ready') return;
  if (state.phase !== 'idle' && !force) return;
  starting = true;
  void (async () => {
    const { shouldLoad, whenIdle } = await import('../../../bot/port/shrunk_loader.mjs');
    if (!force && !shouldLoad(navigator)) {
      set({ phase: 'skipped' });
      starting = false;
      return;
    }
    set({ phase: 'loading', done: 0, total: 0 });
    if (!force) await whenIdle(window);
    try {
      set({ phase: 'ready', api: await load(botBase(), (done, total) => set({ phase: 'loading', done, total })) });
    } catch {
      set({ phase: 'error' });
    } finally {
      starting = false;
    }
  })();
}

/** For tests: forget everything, or put a ready bot in place without loading anything. */
export function resetBot(api?: BotApi): void {
  starting = false;
  set(api ? { phase: 'ready', api } : IDLE);
}
