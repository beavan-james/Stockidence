import { useEffect, useRef, useState } from "react";

const prefersReducedMotion =
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Animate toward `target` with an ease-out curve. Respects
 * prefers-reduced-motion by jumping straight to the value.
 */
export function useCountUp(target: number, durationMs = 900): number {
  const [animated, setAnimated] = useState(0);
  const fromRef = useRef(0);

  useEffect(() => {
    if (prefersReducedMotion) return;
    const from = fromRef.current;
    const start = performance.now();
    let raf: number;

    function tick(now: number) {
      const t = Math.min((now - start) / durationMs, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setAnimated(from + (target - from) * eased);
      if (t < 1) {
        raf = requestAnimationFrame(tick);
      } else {
        fromRef.current = target;
      }
    }

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);

  return prefersReducedMotion ? target : animated;
}
