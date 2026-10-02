import { useNavigate } from "react-router-dom";

import { useIsRanked } from "@/hooks/queries";
import type { Mover } from "@/types/api";
import { cn } from "@/lib/utils";

export function MoverTable({ title, rows }: { title: string; rows: Mover[] }) {
  const navigate = useNavigate();
  const isRanked = useIsRanked();

  return (
    <div>
      <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
      {rows.length === 0 ? (
        <p className="border-t border-line py-4 text-sm text-ink-muted">Nothing to show for this session.</p>
      ) : (
      <div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-muted">
              <th className="px-3 pb-2 font-normal">Ticker</th>
              <th className="px-3 pb-2 text-right font-normal">Price</th>
              <th className="px-3 pb-2 text-right font-normal">Change</th>
              <th className="hidden px-3 pb-2 text-right font-normal sm:table-cell">Volume</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const gain = m.is_gain ?? !m.change_percentage.trim().startsWith("-");
              const ranked = isRanked(m.ticker);
              return (
                <tr
                  key={m.ticker}
                  className={cn(
                    "border-t border-line/60",
                    ranked && "cursor-pointer transition-colors hover:bg-raised/60",
                  )}
                  onClick={ranked ? () => void navigate(`/stocks/${m.ticker}`) : undefined}
                  title={ranked ? "See where it ranks" : undefined}
                >
                  <td className="num px-3 py-2.5 font-semibold">{m.ticker}</td>
                  <td className="num px-3 py-2.5 text-right">${m.price}</td>
                  <td className={cn("num px-3 py-2.5 text-right", gain ? "text-gain" : "text-loss")}>
                    {m.change_display ?? m.change_percentage}
                  </td>
                  <td className="num hidden px-3 py-2.5 text-right text-ink-secondary sm:table-cell">
                    {m.volume_display ?? "N/A"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      )}
    </div>
  );
}
