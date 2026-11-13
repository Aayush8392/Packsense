import { useEffect, useState } from 'react';
import { useChat } from '../lookup/chatState';

/** How far down the page a visitor has to be before the button appears: a twentieth of the way. */
export const SHOW_AFTER = 0.05;

/** Whether the visitor has scrolled `share` of the way down the part of the page that can be scrolled. A page that fits the window never shows it. */
export function pastShare(scrollY: number, scrollHeight: number, windowHeight: number, share = SHOW_AFTER): boolean {
  const scrollable = scrollHeight - windowHeight;
  return scrollable > 0 && scrollY / scrollable >= share;
}

/**
 * The round "Back to the top" button at the bottom right. It sits in the corner, and one step higher, above the question button, when that button is on. It appears once the visitor is 5% of the way down the page, scrolls
 * smoothly to the top (at once for a visitor who asked for less motion) and puts the keyboard focus on the page again, so it is not lost when the button goes.
 * While the question panel is open it is not drawn: the panel stands where the button would be, and a button hidden behind it could still be reached with Tab.
 */
export function ScrollTopButton() {
  const [shown, setShown] = useState(false);
  const { visible: chatOn, open: chatOpen } = useChat();

  useEffect(() => {
    const update = () => setShown(pastShare(window.scrollY, document.documentElement.scrollHeight, window.innerHeight));
    update();
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, []);

  if (!shown || chatOpen) return null;
  const goTop = () => {
    const calm = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top: 0, behavior: calm ? 'auto' : 'smooth' });
    document.getElementById('main')?.focus({ preventScroll: true });
  };

  return (
    <button type="button" className={`scroll-top${chatOn ? ' scroll-top--above-chat' : ''}`} aria-label="Back to the top of the page" onClick={goTop}>
      <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 19V5M6 11l6-6 6 6" />
      </svg>
    </button>
  );
}
