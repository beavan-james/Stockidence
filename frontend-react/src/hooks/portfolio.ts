import { useSyncExternalStore } from "react";

const STORAGE_KEY = "stockidence.portfolio.v1";

interface PortfolioState {
  tickers: string[];
}

function load(): PortfolioState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { tickers: [] };
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed?.tickers)) return { tickers: [] };
    return { tickers: parsed.tickers.filter((t: unknown) => typeof t === "string") };
  } catch {
    return { tickers: [] };
  }
}

let state: PortfolioState = { tickers: [] };
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

export function addToPortfolio(ticker: string) {
  ensureHydrated();
  const symbol = ticker.trim().toUpperCase();
  if (!symbol || state.tickers.includes(symbol)) return;
  commit({ tickers: [...state.tickers, symbol] });
}

export function removeFromPortfolio(ticker: string) {
  ensureHydrated();
  commit({ tickers: state.tickers.filter((t) => t !== ticker) });
}

export function isInPortfolio(ticker: string): boolean {
  ensureHydrated();
  return state.tickers.includes(ticker.trim().toUpperCase());
}
