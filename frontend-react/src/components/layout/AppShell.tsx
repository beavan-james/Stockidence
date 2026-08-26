import { Link, Outlet, useLocation } from "react-router-dom";

import { SearchBar } from "@/components/layout/SearchBar";

export function AppShell() {
  const location = useLocation();

  return (
    <div className="min-h-screen bg-bg text-ink">
      <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-6">
          <Link to="/" className="flex items-center gap-2">
            <img src="/bull.svg" alt="" className="h-5 w-5" />
            <span className="text-[15px] font-semibold tracking-tight">Stockidence</span>
          </Link>
          <div className="flex flex-1 justify-center">
            <SearchBar />
          </div>
          <nav className="flex items-center gap-1 text-sm text-ink-secondary">
            <Link
              to="/"
              className="rounded-lg px-3 py-1.5 transition-colors hover:bg-raised hover:text-ink"
            >
              Discover
            </Link>
            <Link
              to="/portfolio"
              className="rounded-lg px-3 py-1.5 transition-colors hover:bg-raised hover:text-ink"
            >
              Portfolio
            </Link>
            <Link
              to="/docs"
              className="rounded-lg px-3 py-1.5 transition-colors hover:bg-raised hover:text-ink"
            >
              Docs
            </Link>
          </nav>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-8">
        <main key={location.pathname} className="anim-rise min-w-0">
          <Outlet />
        </main>
      </div>

      <footer className="border-t border-line py-6">
        <p className="mx-auto max-w-7xl px-6 text-xs text-ink-muted">
          Deterministic confidence scores from a transparent pipeline — not investment advice.
        </p>
      </footer>
    </div>
  );
}
