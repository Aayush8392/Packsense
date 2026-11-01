import { useEffect, useId, useRef, type FormEvent } from 'react';
import { startBot, useBot, type BotApi } from './botStore';
import { hideChat, setChatOpen, useChat } from './chatState';
import { CHAT_DELAY, ask, pick, setDraft, startAgain, submitDraft, useConversation, type Message } from './chatStore';

// The tests set the pause through this name.
export { CHAT_DELAY };

/** Questions to try, each checked to give a real answer (or, for the second, the fixed reply about food advice). */
export const EXAMPLE_QUESTIONS = ['Which brands fill in their products best?', 'Is this food safe to eat?', 'How often is the data updated?'];

export const WELCOME = 'Ask about the data or how this site works. The answers were written and checked in advance, and nothing is invented while you wait.';

const MAX_CHARACTERS = 300;

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

function Conversation({ api, open }: { api: BotApi; open: boolean }) {
  const { messages, draft, busy, looking } = useConversation();
  const input = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const inputId = useId();

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages, looking, open]);

  function submit(event: FormEvent) {
    event.preventDefault();
    submitDraft(api);
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
                      <button type="button" className="chat-chip" onClick={() => void ask(api, q)} disabled={busy}>{q}</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
          {messages.map((message) => (
            <Bubble key={message.id} message={message} onPick={(id, question) => void pick(api, id, question)} />
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
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <button type="submit" className="chat-send" aria-label="Ask" disabled={busy || draft.trim() === ''}>
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
