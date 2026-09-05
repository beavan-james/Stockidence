import { useEffect, useRef } from "react";

/**
 * Minimal scroll-position indicator: a slim fixed track on the right edge
 * with an accent thumb. Transform/opacity writes only (no re-renders);
 * hidden entirely when the page fits the viewport.
 */
export function ScrollIndicator() {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const thumbRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const track = trackRef.current;
    const thumb = thumbRef.current;
    if (!track || !thumb) return;

    let raf = 0;
    const update = () => {
      raf = 0;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      if (max <= 0) {
        track.style.opacity = "0";
        return;
      }
      track.style.opacity = "1";
      const progress = Math.min(1, Math.max(0, window.scrollY / max));
      const trackH = track.clientHeight;
      const thumbH = Math.max(24, (window.innerHeight / document.documentElement.scrollHeight) * trackH);
      thumb.style.height = `${thumbH}px`;
      thumb.style.transform = `translateY(${progress * (trackH - thumbH)}px)`;
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div
      aria-hidden
      ref={trackRef}
      className="pointer-events-none fixed right-2 top-1/2 z-50 h-[50vh] w-[3px] -translate-y-1/2 rounded-full bg-white/[0.07] opacity-0 transition-opacity duration-300"
    >
      <div
        ref={thumbRef}
        className="w-full rounded-full bg-accent/70 will-change-transform"
        style={{ boxShadow: "0 0 10px color-mix(in srgb, var(--color-accent) 60%, transparent)" }}
      />
    </div>
  );
}
