import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { TIER_NAMES, tierOf } from "@/lib/tiers";
import { SplatDisc } from "@/lib/splatDisc";
import { CONTAINER, cn } from "@/lib/utils";
import type { RankedTicker } from "@/types/api";

/**
 * A full-bleed hero with the ranking drawn as a disc behind the copy (beside it
 * on wide screens, below it on narrow ones). Point at a stock to name it and
 * click to open it; on touch, the first tap names it and a second opens it.
 */
export function SplatHero({
  items,
  pinned,
  children,
  fallback,
}: {
  items: RankedTicker[];
  /** A ticker to light up while nothing is pointed at, e.g. a search match. */
  pinned?: string | null;
  children: ReactNode;
  /** Shown in place of the disc when the browser can't draw it. */
  fallback?: ReactNode;
}) {
  const navigate = useNavigate();
  const hostRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tagRef = useRef<HTMLDivElement>(null);
  const discRef = useRef<SplatDisc | null>(null);
  const pointerType = useRef("mouse");
  const [shown, setShown] = useState(-1);
  // The last stock shown, kept while the label fades out.
  const [labelled, setLabelled] = useState(-1);
  const [tapped, setTapped] = useState(-1);
  const [noGL, setNoGL] = useState(false);
  const n = items.length;

  useEffect(() => {
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host || n === 0) return;
    const disc = new SplatDisc(canvas, host, items, {
      onShow: (i) => {
        setShown(i);
        if (i >= 0) setLabelled(i);
      },
    });
    if (!disc.ok) {
      setNoGL(true);
      return;
    }
    disc.setTag(tagRef.current);
    discRef.current = disc;
    return () => {
      disc.destroy();
      discRef.current = null;
    };
  }, [items, n]);

  const pinnedIndex = pinned ? items.findIndex((r) => r.ticker === pinned) : -1;
  useEffect(() => {
    discRef.current?.setPinned(tapped >= 0 ? tapped : pinnedIndex);
  }, [tapped, pinnedIndex]);

  const label = labelled >= 0 ? items[labelled] : null;

  return (
    <section
      ref={hostRef}
      className={cn(
        // Full bleed: out of the page column to the viewport edges.
        "relative mx-[calc(50%_-_50vw)] flex flex-col overflow-hidden",
        "min-[900px]:min-h-[clamp(640px,calc(100svh_-_64px),820px)]",
      )}
      onPointerDown={(e) => {
        pointerType.current = e.pointerType;
        discRef.current?.move(e.clientX, e.clientY);
      }}
      onPointerMove={(e) => discRef.current?.move(e.clientX, e.clientY)}
      onPointerLeave={() => discRef.current?.leave()}
      onClick={(e) => {
        const disc = discRef.current;
        if (!disc || (e.target as HTMLElement).closest("a, button, input, label")) return;
        const i = disc.stockAt(e.clientX, e.clientY);
        if (pointerType.current !== "touch" || (i >= 0 && i === tapped)) {
          if (i >= 0) void navigate(`/stocks/${items[i].ticker}`);
        } else {
          setTapped(i);
        }
      }}
    >
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={`All ${n} ranked stocks as a disc: the higher a stock ranks, the nearer the bright core it orbits.`}
        className={cn(
          "pixelated relative order-2 block h-80 w-full touch-pan-y bg-black",
          "min-[900px]:absolute min-[900px]:inset-0 min-[900px]:h-full",
          noGL && "hidden",
        )}
      />
      <div className={cn(CONTAINER, "relative order-1 pt-14 min-[900px]:pt-[104px]")}>{children}</div>
      <div className={cn(CONTAINER, "relative order-3 mt-auto pb-9 pt-1 min-[900px]:pt-10")}>
        {noGL && fallback}
      </div>

      <div
        ref={tagRef}
        aria-hidden="true"
        className={cn(
          "group pointer-events-none absolute left-0 top-0 z-10 transition-opacity will-change-transform motion-reduce:transition-none",
          // Appears at once; only fades on the way out.
          shown >= 0 ? "opacity-100 duration-0" : "opacity-0 duration-200",
        )}
      >
        <div className="absolute -left-2 -top-2 h-4 w-4 border border-white/75" />
        {label && (
          <div className="absolute -top-10 left-[18px] whitespace-nowrap bg-black/65 px-2.5 py-[7px] text-xs leading-normal text-ink-secondary group-data-[flip=1]:left-auto group-data-[flip=1]:right-[18px]">
            <span className="block">
              <b className="text-[13px] font-semibold tracking-[0.03em] text-ink">{label.ticker}</b>{" "}
              <span className="num">
                #{label.rank} of {n}
              </span>
            </span>
            <span className="block">
              {label.sector ?? "Sector not on file"} · {TIER_NAMES[tierOf(label.rank, n)]}
            </span>
          </div>
        )}
      </div>
    </section>
  );
}
