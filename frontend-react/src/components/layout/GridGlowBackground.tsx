import { useEffect, useRef } from "react";

/**
 * Grid background where the grid itself brightens around the cursor.
 *
 * Two stacked layers share one grid pattern: a faint static base faded
 * toward the viewport edges, plus a brighter copy revealed through a
 * radial mask that eases toward the pointer. No glow blob, no distortion.
 *
 * Colors derive from theme tokens so a recolor applies automatically.
 * Mask motion is rAF + lerp with direct DOM writes (no re-renders) and
 * fully disabled under prefers-reduced-motion (base grid only).
 */
const GRID =
  "linear-gradient(color-mix(in srgb, var(--color-accent) __ALPHA__%, transparent) 1px, transparent 1px), linear-gradient(90deg, color-mix(in srgb, var(--color-accent) __ALPHA__%, transparent) 1px, transparent 1px)";

const HIGHLIGHT_RADIUS = 300;

export function GridGlowBackground() {
  const highlightRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = highlightRef.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const target = { x: window.innerWidth / 2, y: window.innerHeight * 0.3 };
    const current = { ...target };
    let raf = 0;

    const onMove = (e: PointerEvent) => {
      target.x = e.clientX;
      target.y = e.clientY;
    };
    window.addEventListener("pointermove", onMove, { passive: true });

    const paint = (x: number, y: number) => {
      const mask = `radial-gradient(circle ${HIGHLIGHT_RADIUS}px at ${x}px ${y}px, black 0%, transparent 70%)`;
      el.style.maskImage = mask;
      el.style.webkitMaskImage = mask;
    };
    paint(current.x, current.y);

    const tick = () => {
      current.x += (target.x - current.x) * 0.08;
      current.y += (target.y - current.y) * 0.08;
      paint(current.x, current.y);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      window.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 z-0 overflow-hidden"
    >
      {/* Faint base grid, faded toward the edges */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage: GRID.replaceAll("__ALPHA__", "7"),
          backgroundSize: "32px 32px",
          maskImage:
            "radial-gradient(ellipse 90% 70% at 50% 30%, black 30%, transparent 75%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 90% 70% at 50% 30%, black 30%, transparent 75%)",
        }}
      />
      {/* Brighter grid, revealed only around the cursor */}
      <div
        ref={highlightRef}
        className="absolute inset-0 will-change-[mask-image]"
        style={{
          backgroundImage: GRID.replaceAll("__ALPHA__", "21"),
          backgroundSize: "32px 32px",
        }}
      />
    </div>
  );
}
