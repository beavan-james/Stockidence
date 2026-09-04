import { useSyncExternalStore } from "react";

const STORAGE_KEY = "stockidence.portfolio.v2";
const LEGACY_KEY = "stockidence.portfolio.v1";

export interface Holding {
  symbol: string;
  /** Number of shares. 0 = watchlist entry, no cost basis. */
  shares: number;
  /** Average cost per share. 0 = unknown. */
  avgCost: number;
}

interface PortfolioState {
  holdings: Holding[];
}

function normalizeHolding(raw: unknown): Holding | null {
  if (typeof raw !== "object" || raw === null) return null;
  const h = raw as Record<string, unknown>;
  if (typeof h.symbol !== "string" || !h.symbol.trim()) return null;
  const shares = typeof h.shares === "number" && h.shares >= 0 ? h.shares : 0;
  const avgCost = typeof h.avgCost === "number" && h.avgCost >= 0 ? h.avgCost : 0;
  return { symbol: h.symbol.trim().toUpperCase(), shares, avgCost };
}

function load(): PortfolioState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed?.holdings)) {
        const holdings = parsed.holdings
          .map(normalizeHolding)
          .filter((h: Holding | null): h is Holding => h !== null);
        return { holdings };
      }
    }
    // One-time migration from the v1 ticker list.
    const legacy = localStorage.getItem(LEGACY_KEY);
    if (legacy) {
      const parsed = JSON.parse(legacy);
      if (Array.isArray(parsed?.tickers)) {
        const holdings = parsed.tickers
          .filter((t: unknown) => typeof t === "string" && t.trim())
          .map((t: string) => ({ symbol: t.trim().toUpperCase(), shares: 0, avgCost: 0 }));
        try {
          localStorage.removeItem(LEGACY_KEY);
        } catch {
          // ignore
        }
        return { holdings };
      }
    }
  } catch {
    // Corrupt storage: start empty.
  }
  return { holdings: [] };
}

let state: PortfolioState = { holdings: [] };
let hydrated = false;

function ensureHydrated() {
  if (!hydrated && typeof window !== "undefined") {
    state = load();
    hydrated = true;
  }
}

const listeners = new Set<() => void>();

function commit(next: PortfolioState) {
  state = next;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage full/blocked: keep working in-memory.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function usePortfolio(): PortfolioState {
  ensureHydrated();
  return useSyncExternalStore(subscribe, () => state);
}

function upsert(symbol: string, shares: number, avgCost: number) {
  ensureHydrated();
  const clean = symbol.trim().toUpperCase();
  if (!clean) return;
  const holding: Holding = {
    symbol: clean,
    shares: Math.max(0, shares || 0),
    avgCost: Math.max(0, avgCost || 0),
  };
  const rest = state.holdings.filter((h) => h.symbol !== clean);
  commit({ holdings: [...rest, holding] });
}

export function addHolding(symbol: string, shares = 0, avgCost = 0) {
  upsert(symbol, shares, avgCost);
}

/** Shorthand for watchlist-style adds (no position): preserves an existing holding. */
export function addToPortfolio(ticker: string) {
  ensureHydrated();
  const clean = ticker.trim().toUpperCase();
  if (!clean || state.holdings.some((h) => h.symbol === clean)) return;
  commit({ holdings: [...state.holdings, { symbol: clean, shares: 0, avgCost: 0 }] });
}

export function updateHolding(symbol: string, shares: number, avgCost: number) {
  upsert(symbol, shares, avgCost);
}

export function removeFromPortfolio(ticker: string) {
  ensureHydrated();
  const clean = ticker.trim().toUpperCase();
  commit({ holdings: state.holdings.filter((h) => h.symbol !== clean) });
}

export function isInPortfolio(ticker: string): boolean {
  ensureHydrated();
  return state.holdings.some((h) => h.symbol === ticker.trim().toUpperCase());
}
