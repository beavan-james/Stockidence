import { useEffect } from "react";
import { Link, Outlet, useLocation, useNavigationType } from "react-router-dom";

import logoUrl from "@/assets/logo.svg";
import { useRankings, useWeekly } from "@/hooks/queries";
import { dayLabel, quarterLabel, snapshotLabel } from "@/lib/tiers";
import { CONTAINER, cn } from "@/lib/utils";

type Area = "quarterly" | "weekly" | "market";

const NAV: { area: Area; to: string; label: string }[] = [
  { area: "quarterly", to: "/", label: "Quarterly" },
  { area: "weekly", to: "/week", label: "Weekly" },
  { area: "market", to: "/market", label: "Market" },
];

/** A model's method and stock pages stay under that model in the nav. */
function areaOf(pathname: string): Area | null {
  if (pathname.startsWith("/week")) return "weekly";
  if (pathname.startsWith("/market")) return "market";
  if (pathname === "/" || pathname.startsWith("/model") || pathname.startsWith("/stocks")) return "quarterly";
  return null;
}

function QuarterlyStatus() {
  const { data } = useRankings();
  return data ? `${quarterLabel(data.as_of)} ranking · data to ${snapshotLabel(data.as_of)}` : null;
}

function WeeklyStatus() {
  const { data } = useWeekly();
  return data?.week_of && data.as_of ? `Week of ${dayLabel(data.week_of)} · prices to ${dayLabel(data.as_of)}` : null;
}

export function AppShell() {
  const { pathname } = useLocation();
  const navigationType = useNavigationType();
  const area = areaOf(pathname);

  // New pages open at the top; Back/Forward keep the browser's restored position.
  useEffect(() => {
    if (navigationType !== "POP") window.scrollTo(0, 0);
  }, [pathname, navigationType]);

  return (
    <div className="min-h-screen overflow-x-clip bg-bg text-ink">
      <header className="sticky top-0 z-40 border-b border-white/[0.07] bg-black/70 backdrop-blur-md">
        <div className={cn(CONTAINER, "flex h-16 items-center justify-between gap-6 lg:grid lg:grid-cols-[1fr_auto_1fr]")}>
          <Link
            to="/"
            aria-label="Stockidence"
            className="flex shrink-0 items-center gap-2.5 justify-self-start font-logo text-[28px] leading-none tracking-[-0.01em]"
          >
            <img src={logoUrl} alt="" className="h-[30px] w-[30px]" />
            {/* Icon only on phones, so the nav links fit beside it. */}
            <span className="hidden sm:inline">Stockidence</span>
          </Link>
          <nav className="flex items-center gap-6 whitespace-nowrap text-[15px] text-ink-secondary sm:gap-9">
            {NAV.map((n) => (
              <Link
                key={n.to}
                to={n.to}
                aria-current={area === n.area ? "true" : undefined}
                className={cn(
                  "flex h-16 items-center border-b transition-colors",
                  area === n.area ? "border-accent text-ink" : "border-transparent hover:text-accent",
                )}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <span className="hidden justify-self-end text-[13px] text-ink-muted lg:block">
            {area === "quarterly" && <QuarterlyStatus />}
            {area === "weekly" && <WeeklyStatus />}
          </span>
        </div>
      </header>

      <main className={cn(CONTAINER, "relative")}>
        <Outlet />
      </main>

      <footer className="border-t border-white/[0.07] py-8">
        <div className={cn(CONTAINER, "flex flex-wrap justify-between gap-4 text-xs text-ink-muted")}>
          <p>Stockidence ranks stocks; it doesn't give investment advice.</p>
          <Link to="/docs" className="transition-colors hover:text-accent">
            Documentation
          </Link>
        </div>
      </footer>
    </div>
  );
}
