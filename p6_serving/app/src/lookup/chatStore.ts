import { useSyncExternalStore } from 'react';
import type { BotAnswer, BotApi } from './botStore';

/**
 * The conversation with the question tool. It lives here, in memory only, and not in the panel: closing the panel, hiding the button or moving to another page keeps it,
 * and a refresh of the page starts it afresh. It is never written to the browser's storage, so what a visitor asked is kept nowhere.
 */

/**
 * The rhythm of a reply: the question fades in at once; after `beat` milliseconds the "looking" lines fade in; the answer follows after at least `base` more, a little
 * longer for a longer answer (`perWord` each, up to `max`). A real lookup that takes longer than that is not delayed further. Exported so the tests can set it to zero.
 */
export const CHAT_DELAY = { beat: 600, base: 900, perWord: 9, max: 1700 };

export type Message =
  | { id: number; from: 'you'; text: string }
  | { id: number; from: 'bot'; paragraphs: string[] }
  | { id: number; from: 'bot'; suggestions: { id: string; question: string }[]; close: boolean };

export interface Conversation {
  messages: Message[];
  /** What is typed in the box and not yet sent. */
  draft: string;
  busy: boolean;
  looking: boolean;
}

const EMPTY: Conversation = { messages: [], draft: '', busy: false, looking: false };

let state: Conversation = EMPTY;
// Bumped by "Start again", so an answer that arrives after it is dropped.
let turn = 0;
let nextId = 1;
// The entry the conversation last settled on, handed back with the next question so a short follow-up can lean on it.
let memory: string | null = null;
const listeners = new Set<() => void>();

function set(next: Conversation) {
  state = next;
  listeners.forEach((listener) => listener());
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export const getConversation = (): Conversation => state;

export function useConversation(): Conversation {
  return useSyncExternalStore(subscribe, () => state);
}

function delayFor(answer: BotAnswer): number {
  const text = answer.kind === 'answer' ? answer.parts.map((part) => part.answer).join(' ') : answer.kind === 'reply' ? answer.text : '';
  const words = text.split(/\s+/).filter(Boolean).length;
  return Math.min(CHAT_DELAY.max, CHAT_DELAY.base + words * CHAT_DELAY.perWord);
}

/** Waits for the answer, then until the beat and `delayFor(answer)` have passed since the question was sent. */
async function withPause(lookup: Promise<BotAnswer>): Promise<BotAnswer> {
  const started = Date.now();
  const answer = await lookup;
  const wait = CHAT_DELAY.beat + delayFor(answer) - (Date.now() - started);
  if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
  return answer;
}

function toMessage(id: number, answer: BotAnswer): Message {
  if (answer.kind === 'answer') return { id, from: 'bot', paragraphs: answer.parts.map((part) => part.answer) };
  if (answer.kind === 'suggestions') return { id, from: 'bot', suggestions: answer.items, close: answer.close };
  return { id, from: 'bot', paragraphs: [answer.text] };
}

export function setDraft(draft: string): void {
  set({ ...state, draft });
}

async function run(shownAsYou: string, get: (prevId: string | null) => Promise<BotAnswer>): Promise<void> {
  const mine = turn;
  set({ ...state, messages: [...state.messages, { id: nextId++, from: 'you', text: shownAsYou }], busy: true });
  const lookTimer = setTimeout(() => {
    if (mine === turn) set({ ...state, looking: true });
  }, CHAT_DELAY.beat);
  const answer = await withPause(get(memory).catch((): BotAnswer => ({ kind: 'reply', text: 'Something went wrong while looking for an answer. Please try again.', remember: memory })));
  clearTimeout(lookTimer);
  if (mine !== turn) return;
  memory = answer.remember ?? memory;
  set({ ...state, looking: false, busy: false, messages: [...state.messages, toMessage(nextId++, answer)] });
}

/** Sends a question typed or picked from the examples. */
export function ask(api: BotApi, question: string): Promise<void> {
  return run(question, (prevId) => api.ask(question, prevId));
}

/** Sends a question the visitor picked from the suggestions: the answer to that entry. */
export function pick(api: BotApi, id: string, question: string): Promise<void> {
  return run(question, () => api.answerEntry(id));
}

/** Sends what is typed in the box, then empties the box. */
export function submitDraft(api: BotApi): void {
  const question = state.draft.trim();
  if (question === '' || state.busy) return;
  set({ ...state, draft: '' });
  void ask(api, question);
}

/** The "Start again" link: forgets everything, and drops an answer that is still on its way. */
export function startAgain(): void {
  turn += 1;
  memory = null;
  set({ ...EMPTY });
}

/** For tests: the conversation as it is on a fresh page. */
export function resetConversation(): void {
  startAgain();
  nextId = 1;
}
