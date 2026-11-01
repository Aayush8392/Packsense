import { toggleChatVisible, useChat } from '../lookup/chatState';

/** The "Ask" button in the header: shows or hides the question button at the bottom right of the page. */
export function AskToggle() {
  const { visible } = useChat();
  return (
    <button type="button" className="ask-toggle" aria-pressed={visible} aria-label="Show the question button" title="Show or hide the question button" onClick={toggleChatVisible}>
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" />
      </svg>
      <span aria-hidden="true">Ask</span>
    </button>
  );
}
