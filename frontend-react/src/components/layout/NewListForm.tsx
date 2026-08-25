import { useState } from "react";

import { createList } from "@/hooks/watchlists";

export function NewListForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  function submit() {
    if (!name.trim()) {
      setError("Enter a list name first.");
      return;
    }
    if (createList(name)) {
      setError("That name already exists.");
      return;
    }
    onDone();
  }

  return (
    <div className="space-y-1.5">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
          if (e.key === "Escape") onDone();
        }}
        placeholder="List name"
        className="h-8 w-full rounded-lg border border-line bg-raised px-2.5 text-xs text-ink placeholder:text-ink-muted focus:border-accent/60 focus:outline-none"
      />
      {error && <p className="text-[11px] text-loss">{error}</p>}
      <button
        type="button"
        onClick={submit}
        className="w-full rounded-lg bg-accent px-2 py-1 text-xs font-medium text-bg transition-colors hover:bg-accent-strong"
      >
        Create list
      </button>
    </div>
  );
}
