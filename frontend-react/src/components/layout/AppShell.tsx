import { Link, NavLink, Outlet } from "react-router-dom";

import logoUrl from "@/assets/logo.svg";
import { useRankings } from "@/hooks/queries";
import { quarterLabel, snapshotLabel } from "@/lib/tiers";

const NAV = [
  { to: "/", label: "Rankings", end: true },
  { to: "/model", label: "Model", end: false },
  { to: "/market", label: "Market", end: false },
] as const;

export function AppShell() {
  const rankings = useRankings();

  return (
    <div className="min-h-screen overflow-x-clip bg-bg text-ink">
      <header className="sticky top-0 z-40 border-b border-white/[0.07] bg-bg/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-6 px-6">
          <Link to="/" className="flex items-center gap-2 font-logo text-[28px] leading-none tracking-tight">
            <img src={logoUrl} alt="" className="h-8 w-8" />
            Stockidence
          </Link>
          <nav className="flex items-center gap-7 text-[15px] text-ink-secondary sm:gap-9">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) => (isActive ? "text-ink" : "transition-colors hover:text-ink")}
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <span className="hidden text-[13px] text-ink-muted lg:block">
            {rankings.data
              ? `${quarterLabel(rankings.data.as_of)} ranking · data to ${snapshotLabel(rankings.data.as_of)}`
              : ""}
          </span>
        </div>
      </header>

      <main className="relative mx-auto max-w-7xl px-6">
        <Outlet />
      </main>

      <footer className="mt-10 border-t border-white/[0.07] py-8">
        <div className="mx-auto flex max-w-7xl flex-wrap justify-between gap-4 px-6 text-xs text-ink-muted">
          <p>Stockidence ranks stocks; it doesn't give investment advice.</p>
          <Link to="/docs" className="hover:text-ink">
            Documentation
          </Link>
        </div>
      </footer>
    </div>
  );
}
