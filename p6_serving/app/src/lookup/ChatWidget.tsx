import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { startBot, useBot, type BotAnswer, type BotApi } from './botStore';
import { hideChat, setChatOpen, useChat } from './chatState';

/** Questions to try, each checked to give a real answer (or, for the second, the fixed reply about food advice). */
export const EXAMPLE_QUESTIONS = ['Which brands fill in their products best?', 'Is this food safe to eat?', 'How often is the data updated?'];

export const WELCOME = 'Ask about the data or how this site works. The answers were written and checked in advance, and nothing is invented while you wait.';

const MAX_CHARACTERS = 300;

/**
 * The rhythm of a reply: the question fades in at once; after `beat` milliseconds the "looking" lines fade in; the answer follows after at least `base` more, a little
 * longer for a longer answer (`perWord` each, up to `max`). A real lookup that takes longer than that is not delayed further. Exported so the tests can set it to zero.
 */
export const CHAT_DELAY = { beat: 600, base: 900, perWord: 9, max: 1700 };

function delayFor(answer: BotAnswer): number {
  const text = answer.kind === 'answer' ? answer.parts.map((part) => part.answer).join(' ') : answer.kind === 'reply' ? answer.text : '';
  const words = text.split(/\s+/).filter(Boolean).length;
  return Math.min(CHAT_DELAY.max, CHAT_DELAY.base + words * CHAT_DELAY.perWord);
}

type Message =
  | { id: number; from: 'you'; text: string }
  | { id: number; from: 'bot'; paragraphs: string[] }
  | { id: number; from: 'bot'; suggestions: { id: string; question: string }[]; close: boolean };

/** The small "P" that marks the assistant's messages. */
function Avatar() {
  return <span className="chat-avatar" aria-hidden="true">P</span>;
}

function Bubble({ message, onPick }: { message: Message; onPick: (id: string, question: string) => void }) {
  if (message.from === 'you') {
    return (
      <li className="chat-msg chat-msg--you">
        <div className="chat-bubble">{message.text}</div>
      </li>
    );
  }
  if ('suggestions' in message) {
    return (
      <li className="chat-msg chat-msg--bot">
        <Avatar />
        <div className="chat-body">
          <div className="chat-bubble">
            <p>{message.close ? 'These look closest to your question. Pick the one you mean:' : 'Nothing here matches closely. These are the nearest questions, in case one is what you meant:'}</p>
          </div>
          <ul className="chat-topics">
            {message.suggestions.map((item) => (
              <li key={item.id}>
                <button type="button" className="chat-chip" onClick={() => onPick(item.id, item.question)}>{item.question}</button>
              </li>
            ))}
          </ul>
        </div>
      </li>
    );
  }
  return (
    <li className="chat-msg chat-msg--bot">
      <Avatar />
      <div className="chat-body">
        <div className="chat-bubble">
          {message.paragraphs.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </div>
      </div>
    </li>
  );
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

function Conversation({ api, open }: { api: BotApi; open: boolean }) {
  const [text, setText] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [looking, setLooking] = useState(false);
  const turn = useRef(0);
  const next = useRef(1);
  // The entry the conversation last settled on, handed back with the next question so a short follow-up can lean on it.
  const memory = useRef<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const inputId = useId();

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages, looking]);

  async function run(shownAsYou: string, get: (prevId: string | null) => Promise<BotAnswer>) {
    const mine = turn.current;
    const you: Message = { id: next.current++, from: 'you', text: shownAsYou };
    setMessages((all) => [...all, you]);
    setBusy(true);
    const lookTimer = setTimeout(() => {
      if (mine === turn.current) setLooking(true);
    }, CHAT_DELAY.beat);
    const answer = await withPause(get(memory.current).catch((): BotAnswer => ({ kind: 'reply', text: 'Something went wrong while looking for an answer. Please try again.', remember: memory.current })));
    clearTimeout(lookTimer);
    if (mine !== turn.current) return;
    memory.current = answer.remember ?? memory.current;
    setLooking(false);
    setMessages((all) => [...all, toMessage(next.current++, answer)]);
    setBusy(false);
  }

  function startAgain() {
    turn.current += 1;
    memory.current = null;
    setMessages([]);
    setBusy(false);
    setLooking(false);
  }

  function ask(question: string) {
    void run(question, (prevId) => api.ask(question, prevId));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const question = text.trim();
    if (question === '' || busy) return;
    setText('');
    ask(question);
  }

  return (
    <>
      <div className="chat-log" role="log" aria-live="polite" aria-label="Conversation" ref={log}>
        <ul className="chat-msgs">
          <li className="chat-msg chat-msg--bot">
            <Avatar />
            <div className="chat-body">
              <div className="chat-bubble">
                <p>{WELCOME}</p>
              </div>
              {messages.length === 0 && (
                <ul className="chat-topics">
                  {EXAMPLE_QUESTIONS.map((q) => (
                    <li key={q}>
                      <button type="button" className="chat-chip" onClick={() => ask(q)} disabled={busy}>{q}</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
          {messages.map((message) => (
            <Bubble key={message.id} message={message} onPick={(id, question) => void run(question, () => api.answerEntry(id))} />
          ))}
          {looking && (
            <li className="chat-msg chat-msg--bot">
              <Avatar />
              <div className="chat-body">
                <div className="chat-bubble chat-wait">
                  <p>Looking for the closest answer…</p>
                  <span className="chat-shimmer chat-shimmer--long" aria-hidden="true" />
                  <span className="chat-shimmer" aria-hidden="true" />
                </div>
              </div>
            </li>
          )}
        </ul>
      </div>
      <div className="chat-foot">
        <form className="chat-form" onSubmit={submit} noValidate>
          <label htmlFor={inputId} className="visually-hidden">Ask a question in your own words</label>
          <input
            id={inputId}
            ref={input}
            type="text"
            maxLength={MAX_CHARACTERS}
            autoComplete="off"
            placeholder="Type your question"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button type="submit" className="chat-send" aria-label="Ask" disabled={busy || text.trim() === ''}>
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </form>
        <div className="chat-foot__line">
          <span>Ready-made answers. Nothing is generated.</span>
          <button type="button" className="chat-link" onClick={startAgain} disabled={messages.length === 0}>Start again</button>
        </div>
      </div>
    </>
  );
}

/**
 * The question tool as a chat: a round button at the bottom right of every page opens a panel with the conversation. It waits for the bot to be ready, which starts
 * downloading when the site opens (see botStore), and it stays on screen while the visitor moves between pages. Look from the Stitch export (zips 19 and 20), wording ours.
 */
export function ChatWidget() {
  const bot = useBot();
  const { visible, open } = useChat();
  const launcher = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setChatOpen(false);
        launcher.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  // The panel must end below the sticky header, which is taller when its menu wraps on a narrow screen: the page's CSS gets the header's real height.
  useEffect(() => {
    if (!visible || !open) return;
    const header = document.querySelector('.site-header');
    if (!header) return;
    const apply = () => document.documentElement.style.setProperty('--site-header-h', `${header.getBoundingClientRect().height}px`);
    apply();
    const watcher = typeof ResizeObserver === 'function' ? new ResizeObserver(apply) : null;
    watcher?.observe(header);
    window.addEventListener('resize', apply);
    return () => {
      watcher?.disconnect();
      window.removeEventListener('resize', apply);
    };
  }, [visible, open]);

  if (!visible) return null;

  const progress = bot.phase === 'loading' && bot.total > 0 ? Math.round((bot.done / bot.total) * 100) : null;

  return (
    <div className="chat" data-open={open}>
      {open && (
        <div id={panelId} className="chat-panel" role="dialog" aria-modal="false" aria-labelledby={titleId}>
          <div className="chat-panel__head">
            <span className="chat-mark" aria-hidden="true"><span>P</span></span>
            <div className="chat-panel__titles">
              <h2 id={titleId}>Ask a question</h2>
              <p>Answers written in advance</p>
            </div>
            <button type="button" className="chat-panel__close" onClick={hideChat} aria-label="Hide the question button" title="Hide the question button">
              <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3l18 18M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 8.5 4 9.5 6a14 14 0 0 1-2.4 3.2M6.5 7.5C4.4 8.9 3 11 2.5 12c1 2 4.5 6 9.5 6 1.5 0 2.8-.4 4-.9M9.9 9.9a3 3 0 0 0 4.2 4.2" /></svg>
            </button>
            <button type="button" className="chat-panel__close" onClick={() => { setChatOpen(false); launcher.current?.focus(); }} aria-label="Close the question tool">
              <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
            </button>
          </div>
          {bot.phase === 'ready' && <Conversation api={bot.api} open={open} />}
          {(bot.phase === 'idle' || bot.phase === 'loading') && (
            <div className="chat-state" role="status">
              <p>Getting the question tool ready{progress === null ? '…' : `… ${progress}%`}</p>
              <span className="chat-progress" aria-hidden="true"><span style={{ width: `${progress ?? 8}%` }} /></span>
            </div>
          )}
          {bot.phase === 'skipped' && (
            <div className="chat-state">
              <p>The question tool needs a download of about 14 MB. It was not started because Data Saver is on or the connection is slow.</p>
              <p><button type="button" className="chat-chip" onClick={() => startBot({ force: true })}>Download it now</button></p>
            </div>
          )}
          {bot.phase === 'error' && (
            <div className="chat-state" role="alert">
              <p><strong>The question tool could not be loaded just now.</strong> Check the connection and try again.</p>
              <p><button type="button" className="chat-chip" onClick={() => startBot({ force: true })}>Try again</button></p>
            </div>
          )}
        </div>
      )}
      <button
        ref={launcher}
        type="button"
        className="chat-launcher"
        aria-label="Ask a question"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setChatOpen(!open)}
      >
        <span className="chat-launcher__face">
          {open ? (
            <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
          ) : (
            <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" />
            </svg>
          )}
        </span>
      </button>
    </div>
  );
}
