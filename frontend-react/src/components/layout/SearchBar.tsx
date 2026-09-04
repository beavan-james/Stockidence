import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { TickerAutocomplete } from "@/components/layout/TickerAutocomplete";

/**
 * Global ticker search with autocomplete over the landed symbol universe.
 * Enter jumps straight to the typed symbol; the profile page's coverage
 * check reports unknown tickers with the API's message.
 */
export function SearchBar() {
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  function go(symbol: string) {
    if (!symbol.trim()) return;
    setQuery("");
    void navigate(`/stocks/${encodeURIComponent(symbol.trim().toUpperCase())}`);
  }

  return (
    <div className="w-full max-w-md">
      <TickerAutocomplete value={query} onValueChange={setQuery} onPick={go} />
    </div>
  );
}
