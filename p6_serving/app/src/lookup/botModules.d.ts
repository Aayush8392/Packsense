// The question bot's own modules live in p6_serving/bot/port as plain JavaScript (they also run in Node, where their tests are). Only what the app uses is typed.

declare module '*/shrunk_loader.mjs' {
  export interface BotParts {
    version: string;
    [part: string]: unknown;
  }
  export function shouldLoad(nav: unknown): boolean;
  export function whenIdle(win: unknown, timeoutMs?: number): Promise<void>;
  export function loadBundle(options: {
    base: string;
    fetchImpl?: typeof fetch;
    cacheStorage?: unknown;
    onProgress?: (done: number, total: number) => void;
  }): Promise<BotParts>;
}

declare module '*/shrunk_bot.mjs' {
  import type { BotParts } from '*/shrunk_loader.mjs';
  export type Shown =
    | { kind: 'answer'; entries: string[]; combined: boolean; hub: boolean }
    | { kind: 'suggestions'; entries: string[]; close: boolean }
    | { kind: 'reply'; action: string; text: string };
  export interface ShrunkBot {
    ask(text: string, prevId?: string | null): Promise<{ shown: Shown; remember: string | null }>;
    entry(id: string): { question: string; answer: string };
  }
  export function createShrunkBot(parts: BotParts): ShrunkBot;
}

declare module '*/make_bot_bundle.mjs' {
  export const FILES: Record<string, string>;
  export function makeBundle(out: string, base?: URL): { totalBytes: number };
}
