import { Link, Outlet, useLocation } from "react-router-dom";

import { GridGlowBackground } from "@/components/layout/GridGlowBackground";
import { SearchBar } from "@/components/layout/SearchBar";

export function AppShell() {
    const location = useLocation();

    return (
        <div className="min-h-screen bg-bg text-ink">
            <GridGlowBackground />
            <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur">
                <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-6">
                    <Link to="/" className="title-glow flex items-center gap-2.5">
                        <img src="/bull.svg" alt="" className="h-8 w-8" />
                        <span className="text-lg font-semibold tracking-tight">
                            Stockidence
                        </span>
                    </Link>
                    <div className="flex flex-1 justify-center">
                        <SearchBar />
                    </div>
                    <nav className="flex items-center gap-1 text-sm text-ink-secondary">
                        <Link
                            to="/"
                            className="nav-glow rounded-lg px-3 py-1.5"
                        >
                            Model
                        </Link>
                        <Link
                            to="/discover"
                            className="nav-glow rounded-lg px-3 py-1.5"
                        >
                            Discover
                        </Link>
                        <Link
                            to="/portfolio"
                            className="nav-glow rounded-lg px-3 py-1.5"
                        >
                            Portfolio
                        </Link>
                        <Link
                            to="/docs"
                            className="nav-glow rounded-lg px-3 py-1.5"
                        >
                            Docs
                        </Link>
                    </nav>
                </div>
            </header>

            <div className="relative z-10 mx-auto max-w-7xl px-6 py-8">
                <main key={location.pathname} className="anim-rise min-w-0">
                    <Outlet />
                </main>
            </div>

            <footer className="relative z-10 border-t border-line py-6">
                <p className="mx-auto max-w-7xl px-6 text-xs text-ink-muted">
                    Information about all your favorite stocks - not investment
                    advice.
                </p>
            </footer>
        </div>
    );
}
