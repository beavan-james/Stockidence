import { useSyncExternalStore } from "react";

/**
 * Watchlists persisted to localStorage, shared app-wide via a tiny
 * external store so the rail and the profile page stay in sync.
 */

export interface Watchlist {
  name: string;
  tickers: string[];
}

interface WatchlistState {
  lists: Watchlist[];
  active: string;
}

const STORAGE_KEY = "stockidence.watchlists.v1";

function load(): WatchlistState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { lists: [], active: "" };
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed?.lists)) return { lists: [], active: "" };
    const lists = parsed.lists.filter(
      (l: unknown): l is Watchlist =>
        typeof l === "object" && l !== null && typeof (l as Watchlist).name === "string",
    );
    return {
      lists,
      active: typeof parsed.active === "string" ? parsed.active : "",
    };
  } catch {
    return { lists: [], active: "" };
  }
}

let state: WatchlistState = { lists: [], active: "" };
let hydrated = false;

function ensureHydrated() {
  if (!hydrated && typeof window !== "undefined") {
    state = load();
    hydrated = true;
  }
}

const listeners = new Set<() => void>();

function commit(next: WatchlistState) {
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

export function useWatchlists(): WatchlistState {
  ensureHydrated();
  return useSyncExternalStore(subscribe, () => state);
}

export function createList(name: string): string | null {
  ensureHydrated();
  const trimmed = name.trim();
  if (!trimmed || state.lists.some((l) => l.name === trimmed)) return "error";
  commit({ lists: [...state.lists, { name: trimmed, tickers: [] }], active: trimmed });
  return null;
}

export function deleteList(name: string) {
  ensureHydrated();
  commit({
    lists: state.lists.filter((l) => l.name !== name),
    active: state.active === name ? "" : state.active,
  });
}

export function setActive(name: string) {
  ensureHydrated();
  commit({ ...state, active: name });
}

export function addToActive(ticker: string) {
  ensureHydrated();
  const symbol = ticker.trim().toUpperCase();
  if (!symbol || !state.active) return;
  commit({
    ...state,
    lists: state.lists.map((l) =>
      l.name === state.active && !l.tickers.includes(symbol)
        ? { ...l, tickers: [...l.tickers, symbol] }
        : l,
    ),
  });
}

export function removeFromActive(ticker: string) {
  ensureHydrated();
  commit({
    ...state,
    lists: state.lists.map((l) =>
      l.name === state.active ? { ...l, tickers: l.tickers.filter((t) => t !== ticker) } : l,
    ),
  });
}
