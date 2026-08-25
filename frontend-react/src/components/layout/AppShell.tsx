import { Link, Outlet } from "react-router-dom";

import { SearchBar } from "@/components/layout/SearchBar";

export function AppShell() {
  return (
    <div className="min-h-screen bg-bg text-ink">
      <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-6">
          <Link to="/" className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-accent" />
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
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
      <footer className="border-t border-line py-6">
        <p className="mx-auto max-w-6xl px-6 text-xs text-ink-muted">
          Deterministic confidence scores from a transparent pipeline — not investment advice.
        </p>
      </footer>
    </div>
  );
}
