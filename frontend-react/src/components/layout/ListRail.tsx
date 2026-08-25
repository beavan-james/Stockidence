import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PanelLeftClose, PanelLeftOpen, Plus, X } from "lucide-react";

import { NewListForm } from "@/components/layout/NewListForm";
import { deleteList, removeFromActive, setActive, useWatchlists } from "@/hooks/watchlists";
import { cn } from "@/lib/utils";

const COLLAPSE_KEY = "stockidence.rail-collapsed";

function readCollapsed(): boolean {
  return localStorage.getItem(COLLAPSE_KEY) === "1";
}

/** Left rail of user watchlists, persisted to localStorage. */
export function ListRail() {
  const { lists, active } = useWatchlists();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [showNewList, setShowNewList] = useState(false);
  const navigate = useNavigate();

  function toggleCollapse() {
    setCollapsed((c) => {
      localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      return !c;
    });
  }

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={toggleCollapse}
        aria-label="Show lists"
        className="sticky top-20 h-8 w-8 shrink-0 rounded-lg border border-line text-ink-muted transition-colors hover:bg-raised hover:text-ink"
      >
        <PanelLeftOpen size={14} className="mx-auto" />
      </button>
    );
  }

  return (
    <aside className="sticky top-20 w-56 shrink-0 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Lists</h2>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={() => setShowNewList(true)}
            aria-label="New list"
            className="rounded-md p-1 text-ink-muted transition-colors hover:bg-raised hover:text-ink"
          >
            <Plus size={14} />
          </button>
          <button
            type="button"
            onClick={toggleCollapse}
            aria-label="Hide lists"
            className="rounded-md p-1 text-ink-muted transition-colors hover:bg-raised hover:text-ink"
          >
            <PanelLeftClose size={14} />
          </button>
        </div>
      </div>

      {showNewList && <NewListForm onDone={() => setShowNewList(false)} />}

      {!showNewList && lists.length === 0 && (
        <p className="text-xs leading-relaxed text-ink-muted">
          Create a list to keep an eye on tickers. Lists live in this browser.
        </p>
      )}

      <ul className="space-y-2">
        {lists.map((list) => {
          const isActive = list.name === active;
          return (
            <li key={list.name}>
              <div
                className={cn(
                  "cursor-pointer rounded-xl border px-3 py-2 transition-colors",
                  isActive ? "border-accent/40 bg-accent-dim" : "border-line bg-surface hover:border-line",
                )}
                onClick={() => setActive(list.name)}
              >
                <div className="flex items-center justify-between">
                  <span
                    className={cn(
                      "truncate text-xs font-medium",
                      isActive ? "text-accent-strong" : "text-ink-secondary",
                    )}
                    title={list.name}
                  >
                    {list.name}
                  </span>
                  <button
                    type="button"
                    aria-label={`Delete ${list.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteList(list.name);
                    }}
                    className="text-ink-muted/60 transition-colors hover:text-loss"
                  >
                    <X size={12} />
                  </button>
                </div>
                {isActive && list.tickers.length > 0 && (
                  <ul className="mt-2 space-y-0.5">
                    {list.tickers.map((ticker) => (
                      <li key={ticker} className="group flex items-center justify-between">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void navigate(`/stocks/${ticker}`);
                          }}
                          className="num rounded px-1 py-0.5 text-left text-[11px] text-ink transition-colors hover:text-accent-strong"
                        >
                          {ticker}
                        </button>
                        <button
                          type="button"
                          aria-label={`Remove ${ticker}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            removeFromActive(ticker);
                          }}
                          className="opacity-0 transition-opacity group-hover:opacity-100"
                        >
                          <X size={10} className="text-ink-muted hover:text-loss" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
