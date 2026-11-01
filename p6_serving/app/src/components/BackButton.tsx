import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { popStep, useTrail, type Step } from '../nav/jumpStore';

/** How long the button stays open, with its words, before it folds into a round arrow. */
export const FOLD_AFTER_MS = 2000;

/**
 * The floating Back button at the bottom left. It appears when a jump has left a step on the trail, says where it goes back to, and returns there with the page's
 * choices and scroll position as they were. Two seconds after it appears (or after the pointer or focus leaves it) it folds into a round arrow; hovering or focusing it
 * opens it again. Each press goes back one step.
 */
export function BackButton() {
  const trail = useTrail();
  const navigate = useNavigate();
  const top = trail[trail.length - 1];
  // Open while the pointer or focus is on it, and for two seconds after a jump (or after the pointer or focus leaves); then folded.
  const [held, setHeld] = useState(false);
  // The step the button has folded for: a newer step opens it again.
  const [foldedFor, setFoldedFor] = useState<Step | null>(null);
  const open = held || foldedFor !== top;

  useEffect(() => {
    if (!top || held) return;
    const timer = setTimeout(() => setFoldedFor(top), FOLD_AFTER_MS);
    return () => clearTimeout(timer);
  }, [top, held]);

  const hold = () => setHeld(true);
  const release = () => {
    setFoldedFor(null);
    setHeld(false);
  };

  if (!top) return null;
  const label = `Back to ${top.label}`;
  const goBack = () => {
    const step = popStep();
    if (step) navigate(step.path, { state: { restoreScroll: step.scroll } });
  };

  return (
    <button
      type="button"
      className="back-button"
      data-open={open}
      aria-label={label}
      onClick={goBack}
      onMouseEnter={hold}
      onMouseLeave={release}
      onFocus={hold}
      onBlur={release}
    >
      <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M19 12H5M11 6l-6 6 6 6" />
      </svg>
      <span className="back-button__label" aria-hidden="true">{label}</span>
    </button>
  );
}
