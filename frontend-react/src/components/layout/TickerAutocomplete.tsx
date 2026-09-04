import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { client } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * Ticker autocomplete input shared by the header SearchBar and the
 * portfolio add-holding form. Debounced lookup over the landed symbol
 * universe with keyboard navigation; Enter picks the highlighted
 * suggestion (or the raw typed symbol).
 */
export function TickerAutocomplete({
  value,
  onValueChange,
  onPick,
  placeholder = "Search any US-listed ticker…",
  className,
  ariaLabel = "Ticker search",
}: {
  value: string;
  onValueChange: (value: string) => void;
  onPick: (symbol: string) => void;
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
}) {
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value.trim()), 250);
    return () => clearTimeout(timer);
  }, [value]);

  useEffect(() => {
    function onClickOutside(event: MouseEvent) {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const { data: suggestions = [] } = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => client.search(debounced),
    enabled: debounced.length > 0,
    staleTime: 60_000,
  });

  function pick(symbol: string) {
    if (!symbol.trim()) return;
    setOpen(false);
    setActive(-1);
    onPick(symbol.trim().toUpperCase());
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, suggestions.length - 1));
      setOpen(true);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, -1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      pick(active >= 0 ? suggestions[active].symbol : value);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={boxRef} className={cn("relative w-full", className)}>
      <Input
        value={value}
        placeholder={placeholder}
        onChange={(e) => {
          onValueChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        aria-label={ariaLabel}
        className="num"
      />
      {open && debounced && (
        <div className="absolute top-full z-50 mt-2 w-full overflow-hidden rounded-xl border border-line bg-surface shadow-2xl shadow-black/50">
          {suggestions.length === 0 ? (
            <p className="px-4 py-3 text-sm text-ink-muted">
              No symbols match “{debounced}”.
            </p>
          ) : (
            <ul>
              {suggestions.map((s, i) => (
                <li key={`${s.mic}-${s.symbol}`}>
                  <button
                    type="button"
                    onMouseEnter={() => setActive(i)}
                    onClick={() => pick(s.symbol)}
                    className={cn(
                      "flex w-full items-baseline gap-3 px-4 py-2.5 text-left",
                      i === active ? "bg-accent-dim" : "",
                    )}
                  >
                    <span className="num text-sm font-semibold text-accent-strong">
                      {s.symbol}
                    </span>
                    <span className="truncate text-xs text-ink-secondary">
                      {s.description}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
