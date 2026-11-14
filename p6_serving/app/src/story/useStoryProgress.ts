import { useEffect, useRef, type RefObject } from 'react';
import { sceneVars } from './scene';
import { beatAt, clamp01 } from './timeline';

/**
 * Turns the scroll position into the story's progress (0 at the top of the tall section, 1 at its end) and writes the scene's custom properties on
 * the stage once a frame. Nothing here causes a React render except a change of stage, which `onBeat` reports. `fixed` (the development slider) holds
 * the story at one progress instead of following the scroll.
 */
export function useStoryProgress(
  section: RefObject<HTMLElement | null>,
  stage: RefObject<HTMLElement | null>,
  onBeat: (beat: number) => void,
  fixed: number | null,
): void {
  const beatCallback = useRef(onBeat);
  const fixedRef = useRef(fixed);
  const redraw = useRef<() => void>(() => undefined);

  useEffect(() => {
    const wrap = section.current;
    const stageEl = stage.current;
    if (!wrap || !stageEl) return;
    let frame = 0;
    let lastBeat = -1;
    let lastP = -1;

    const draw = () => {
      frame = 0;
      let p: number;
      if (fixedRef.current !== null) p = clamp01(fixedRef.current);
      else {
        const top = parseFloat(getComputedStyle(stageEl).top) || 0;
        const box = wrap.getBoundingClientRect();
        const run = box.height - stageEl.offsetHeight;
        p = run > 0 ? clamp01((top - box.top) / run) : 0;
      }
      if (p === lastP) return;
      lastP = p;
      for (const [name, value] of Object.entries(sceneVars(p))) stageEl.style.setProperty(name, value);
      const beat = beatAt(p);
      if (beat !== lastBeat) {
        lastBeat = beat;
        beatCallback.current(beat);
      }
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(draw);
    };
    redraw.current = () => {
      lastP = -1;
      schedule();
    };

    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    schedule();
    return () => {
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [section, stage]);

  useEffect(() => {
    beatCallback.current = onBeat;
  });

  useEffect(() => {
    fixedRef.current = fixed;
    redraw.current();
  }, [fixed]);
}
