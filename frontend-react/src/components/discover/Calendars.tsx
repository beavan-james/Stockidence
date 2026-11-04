import { useNavigate } from "react-router-dom";
import { useMemo } from "react";

import { useIsRanked } from "@/hooks/queries";
import { dayLabel } from "@/lib/tiers";
import type { EarningsRelease, IpoListing } from "@/types/api";
import { cn } from "@/lib/utils";

const MAX_VISIBLE = 10;
const HEADING = "mb-4 font-medium text-2xl tracking-tight";
const SCROLL = "overflow-y-auto no-scrollbar";

const HOURS: Record<string, string> = { amc: "After close", bmo: "Before open" };

/** IPO status as plain text: priced in a softened accent, the rest muted. */
function ipoStatus(status: string | null): { label: string; cls: string } | null {
  if (!status) return null;
  const label = status.charAt(0).toUpperCase() + status.slice(1);
  return { label, cls: status === "priced" ? "text-accent/70" : "text-ink-muted" };
}

export function IpoCalendar({ listings }: { listings: IpoListing[] }) {
  const sorted = useMemo(
    () => [...listings].sort((a, b) => (b.date ?? "").localeCompare(a.date ?? "")),
    [listings],
  );

  return (
    <div>
      <h3 className={HEADING}>IPOs</h3>
      <div className={cn(SCROLL, sorted.length > MAX_VISIBLE && "max-h-96")}>
        <table className="data-table">
          <thead className="sticky top-0 bg-bg">
            <tr>
              <th>Date</th>
              <th>Symbol</th>
              <th>Company</th>
              <th className="text-right">Price</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((ipo, i) => {
              const status = ipoStatus(ipo.status);
              return (
                <tr key={`${ipo.symbol ?? i}-${ipo.date}`}>
                  <td className="num whitespace-nowrap text-ink-secondary">{dayLabel(ipo.date)}</td>
                  <td>
                    <span className="num ticker">{ipo.symbol ?? "—"}</span>
                    {status && <span className={cn("ml-2 text-[11px]", status.cls)}>{status.label}</span>}
                  </td>
                  <td className="max-w-40 truncate text-ink-secondary">{ipo.name}</td>
                  <td className={cn("num text-right", !ipo.price && "text-ink-muted")}>
                    {ipo.price ? `$${ipo.price}` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function EarningsCalendar({ releases }: { releases: EarningsRelease[] }) {
  const navigate = useNavigate();
  const isRanked = useIsRanked();

  const sorted = useMemo(
    () =>
      [...releases].sort((a, b) => {
        const dateCmp = (a.date ?? "").localeCompare(b.date ?? "");
        if (dateCmp !== 0) return dateCmp;
        return (b.revenue_estimate ?? 0) - (a.revenue_estimate ?? 0);
      }),
    [releases],
  );

  return (
    <div>
      <h3 className={HEADING}>Earnings</h3>
      <div className={cn(SCROLL, sorted.length > MAX_VISIBLE && "max-h-96")}>
        <table className="data-table">
          <thead className="sticky top-0 bg-bg">
            <tr>
              <th>Date</th>
              <th>Symbol</th>
              <th>When</th>
              <th className="text-right">EPS est.</th>
              <th className="text-right">Rev est.</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((e, i) => (
              <tr
                key={`${e.symbol}-${i}`}
                className={cn(isRanked(e.symbol) && "row-link")}
                onClick={isRanked(e.symbol) ? () => void navigate(`/stocks/${e.symbol}`) : undefined}
              >
                <td className="num whitespace-nowrap text-ink-secondary">{dayLabel(e.date)}</td>
                <td className="num ticker">{e.symbol}</td>
                <td className="whitespace-nowrap text-[11px] text-ink-muted">{HOURS[e.hour ?? ""] ?? "—"}</td>
                <td className={cn("num text-right", e.eps_estimate == null && "text-ink-muted")}>
                  {e.eps_estimate?.toFixed(2) ?? "—"}
                </td>
                <td className="num text-right text-ink-secondary">{e.revenue_estimate_display ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
