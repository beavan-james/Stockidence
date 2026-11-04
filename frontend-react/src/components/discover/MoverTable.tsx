import { useNavigate } from "react-router-dom";

import { useIsRanked } from "@/hooks/queries";
import type { Mover } from "@/types/api";
import { cn } from "@/lib/utils";

/** "$120.00", or four decimals under a dollar, so a price column reads evenly. */
function money(price: string): string {
  const n = Number(price);
  return Number.isFinite(n) ? `$${n.toFixed(n < 1 ? 4 : 2)}` : `$${price}`;
}

export function MoverTable({ title, rows }: { title: string; rows: Mover[] }) {
  const navigate = useNavigate();
  const isRanked = useIsRanked();

  return (
    <div>
      <h3 className="mb-4 font-medium text-2xl tracking-tight">{title}</h3>
      {rows.length === 0 ? (
        <p className="border-t border-line py-4 text-sm text-ink-muted">Nothing to show for this session.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Stock</th>
              <th className="text-right">Price</th>
              <th className="text-right">Change</th>
              {/* Three tables share the row at lg, so volume waits for xl. */}
              <th className="hidden text-right sm:table-cell lg:hidden xl:table-cell">Volume</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const gain = m.is_gain ?? !m.change_percentage.trim().startsWith("-");
              const ranked = isRanked(m.ticker);
              return (
                <tr
                  key={m.ticker}
                  className={cn(ranked && "row-link")}
                  onClick={ranked ? () => void navigate(`/stocks/${m.ticker}`) : undefined}
                  title={ranked ? "See where it ranks" : undefined}
                >
                  <td className="num ticker">{m.ticker}</td>
                  <td className="num text-right">{money(m.price)}</td>
                  <td className={cn("num whitespace-nowrap text-right", gain ? "text-gain" : "text-loss")}>
                    {m.change_display ?? m.change_percentage}
                  </td>
                  <td className="num hidden text-right text-ink-secondary sm:table-cell lg:hidden xl:table-cell">
                    {m.volume_display ?? "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
