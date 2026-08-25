import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EarningsRelease, IpoListing } from "@/types/api";

function hourBadge(hour: string | null): string {
  if (hour === "amc") return "After close";
  if (hour === "bmo") return "Before open";
  return "—";
}

export function IpoCalendar({ listings }: { listings: IpoListing[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>IPO calendar</CardTitle>
      </CardHeader>
      <CardContent className="px-2 pb-2 pt-3">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-muted">
              <th className="px-3 pb-2 font-normal">Date</th>
              <th className="px-3 pb-2 font-normal">Symbol</th>
              <th className="px-3 pb-2 font-normal">Company</th>
              <th className="px-3 pb-2 font-normal">Price</th>
            </tr>
          </thead>
          <tbody>
            {listings.map((ipo, i) => (
              <tr key={`${ipo.symbol ?? i}-${ipo.date}`} className="border-t border-line/60">
                <td className="num px-3 py-2.5 text-ink-secondary">{ipo.date}</td>
                <td className="num px-3 py-2.5 font-semibold">
                  {ipo.symbol ?? "—"}
                </td>
                <td className="max-w-40 truncate px-3 py-2.5 text-ink-secondary">{ipo.name}</td>
                <td className="num px-3 py-2.5 text-right text-ink-secondary">
                  {ipo.price ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

export function EarningsCalendar({ releases }: { releases: EarningsRelease[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Earnings calendar</CardTitle>
      </CardHeader>
      <CardContent className="px-2 pb-2 pt-3">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-muted">
              <th className="px-3 pb-2 font-normal">Date</th>
              <th className="px-3 pb-2 font-normal">Symbol</th>
              <th className="px-3 pb-2 font-normal">When</th>
              <th className="px-3 pb-2 text-right font-normal">EPS est.</th>
              <th className="px-3 pb-2 text-right font-normal">Rev est.</th>
            </tr>
          </thead>
          <tbody>
            {releases.map((e, i) => (
              <tr key={`${e.symbol}-${i}`} className="border-t border-line/60">
                <td className="num px-3 py-2.5 text-ink-secondary">{e.date}</td>
                <td className="num px-3 py-2.5 font-semibold">{e.symbol}</td>
                <td className="px-3 py-2.5 text-xs text-ink-muted">{hourBadge(e.hour)}</td>
                <td className="num px-3 py-2.5 text-right">
                  {e.eps_estimate?.toFixed(2) ?? "—"}
                </td>
                <td className="num px-3 py-2.5 text-right text-ink-secondary">
                  {e.revenue_estimate_display ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
