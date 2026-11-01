// @vitest-environment node
// The whole question tool end to end with the real bundle: chunks, loader, shrunk model, matcher, live figures. Skipped without the generated files
// (node p6_serving/bot/port/make_bot_bundle.mjs needs them; see p6_serving/bot/port).
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { afterAll, describe, expect, it, vi } from 'vitest';
import { FILES, makeBundle } from '../../../bot/port/make_bot_bundle.mjs';
import { loadBotApi } from './botStore';

const PORT = join(import.meta.dirname, '..', '..', '..', 'bot', 'port');
const ready = Object.values(FILES).every((f) => existsSync(join(PORT, f)));
const out = ready ? mkdtempSync(join(tmpdir(), 'packsense-app-bot-')) : '';
afterAll(() => out && rmSync(out, { recursive: true, force: true }));

const SITE_STATUS = 'built_at_utc,first_complete_day,last_complete_day,products_held_all,products_held_india\n2026-11-01T09:01:07Z,2026-10-01,2026-10-31,1234567,24932\n';

describe.skipIf(!ready)('the question tool with the real bundle', () => {
  it('answers the example questions and fills the live figures it can', async () => {
    makeBundle(out, pathToFileURL(`${PORT}/`));
    vi.stubGlobal('fetch', async (url: string) => {
      const name = String(url).split('/').pop() ?? '';
      if (name === 'site_status.csv') return new Response(SITE_STATUS);
      const path = join(out, name);
      return existsSync(path) ? new Response(readFileSync(path)) : new Response('', { status: 404 });
    });
    const api = await loadBotApi('/data/bot/');
    const text = (a: Awaited<ReturnType<typeof api.ask>>) => (a.kind === 'answer' ? a.parts.map((p) => p.answer).join(' ') : a.kind === 'reply' ? a.text : '');

    const updated = await api.ask('How often is the data updated?');
    expect(updated.kind).toBe('answer');
    expect(text(updated)).toMatch(/day|daily/i);

    const advice = await api.ask('Is this food safe to eat?');
    expect(advice.kind).toBe('reply');
    expect(text(advice)).toMatch(/can't tell you whether a food is safe/);

    const brands = await api.ask('Which brands fill in their products best?');
    expect(brands.kind).not.toBe('reply');

    const held = await api.ask('How many products does PackSense hold?');
    expect(held.kind).toBe('answer');
    expect(text(held)).toContain('1,234,567');
    expect(text(held)).not.toMatch(/\{[a-z_]+\}/);

    const unpublished = await api.ask('How many brands are there?');
    expect(text(unpublished)).not.toMatch(/\{[a-z_]+\}/);
  }, 120_000);

  it('offers up to four different nearest questions for a vague one, and each is answered exactly; a follow-up gets the memory', async () => {
    const api = await loadBotApi('/data/bot/');
    const vague = await api.ask('data');
    expect(['answer', 'suggestions', 'reply']).toContain(vague.kind);
    const lead = vague.kind === 'suggestions' ? vague : await api.ask('stuff about numbers somewhere');
    if (lead.kind === 'suggestions') {
      expect(lead.items.length).toBeGreaterThan(0);
      expect(lead.items.length).toBeLessThanOrEqual(4);
      expect(new Set(lead.items.map((i) => i.question)).size).toBe(lead.items.length);
      const picked = await api.answerEntry(lead.items[0].id);
      expect(picked.kind).toBe('answer');
      expect(picked.remember).toBe(lead.items[0].id);
    }
    const first = await api.ask('How often is the data updated?');
    expect(typeof first.remember).toBe('string');
    const follow = await api.ask('and the India one?', first.remember);
    expect(['answer', 'suggestions', 'reply']).toContain(follow.kind);
  }, 120_000);
});
