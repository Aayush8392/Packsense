import { useEffect, useRef, useState } from 'react';

const FALLBACK_WIDTH = 640;

/**
 * The drawn width of a chart's container and the size of one text line (the root font size, so margins follow the visitor's text size).
 * A chart is drawn at its real width, not scaled from a fixed picture, so its text never shrinks on a phone.
 */
export function useChartBox() {
  const ref = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ width: FALLBACK_WIDTH, unit: 16 });

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      const width = Math.round(element.getBoundingClientRect().width);
      const unit = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
      if (width > 0) setBox((previous) => (previous.width === width && previous.unit === unit ? previous : { width, unit }));
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return { ref, ...box };
}
