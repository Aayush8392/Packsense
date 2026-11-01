import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getBotState, resetBot, startBot, type BotApi } from './botStore';

const FAKE: BotApi = { ask: async () => ({ kind: 'reply', text: 'x', remember: null }), answerEntry: async () => ({ kind: 'reply', text: 'y', remember: null }) };

beforeEach(() => {
  resetBot();
  (window as unknown as { requestIdleCallback: (cb: () => void) => void }).requestIdleCallback = (cb) => cb();
});
afterEach(() => {
  vi.unstubAllGlobals();
  delete (window as unknown as { requestIdleCallback?: unknown }).requestIdleCallback;
  resetBot();
});

const connection = (c: object) => vi.stubGlobal('navigator', { ...navigator, connection: c });

describe('starting the bot', () => {
  it('loads once the site is idle, reports progress, and becomes ready', async () => {
    const load = vi.fn(async (_base: string, onProgress: (done: number, total: number) => void = () => {}) => {
      onProgress(5, 10);
      expect(getBotState()).toEqual({ phase: 'loading', done: 5, total: 10 });
      return FAKE;
    });
    startBot({ load });
    await vi.waitFor(() => expect(getBotState().phase).toBe('ready'));
    expect(load).toHaveBeenCalledTimes(1);
    expect(load.mock.calls[0][0]).toMatch(/data\/bot\/$/);
  });

  it('starts only once, however often it is called', async () => {
    const load = vi.fn(async () => FAKE);
    startBot({ load });
    startBot({ load });
    await vi.waitFor(() => expect(getBotState().phase).toBe('ready'));
    startBot({ load });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('downloads nothing on Data Saver or a slow connection, until the visitor asks', async () => {
    const load = vi.fn(async () => FAKE);
    connection({ saveData: true });
    startBot({ load });
    await vi.waitFor(() => expect(getBotState().phase).toBe('skipped'));
    expect(load).not.toHaveBeenCalled();
    startBot({ load });
    expect(getBotState().phase).toBe('skipped');
    startBot({ force: true, load });
    await vi.waitFor(() => expect(getBotState().phase).toBe('ready'));
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('skips on 3G as well', async () => {
    connection({ effectiveType: '3g' });
    startBot({ load: vi.fn(async () => FAKE) });
    await vi.waitFor(() => expect(getBotState().phase).toBe('skipped'));
  });

  it('shows an error when the files cannot be loaded, and a retry can succeed', async () => {
    startBot({ load: async () => { throw new Error('offline'); } });
    await vi.waitFor(() => expect(getBotState().phase).toBe('error'));
    startBot({ load: async () => FAKE });
    expect(getBotState().phase).toBe('error');
    startBot({ force: true, load: async () => FAKE });
    await vi.waitFor(() => expect(getBotState().phase).toBe('ready'));
  });
});
