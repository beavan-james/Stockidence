import { useNavigate } from "react-router-dom";
import { useMemo } from "react";
import { motion, type Variants } from "framer-motion";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EarningsRelease, IpoListing } from "@/types/api";
import { cn } from "@/lib/utils";

const ease = [0.22, 1, 0.36, 1] as const;
const MAX_VISIBLE = 10;

const rowVariants: Variants = {
  hidden: { opacity: 0, x: -6 },
  visible: { opacity: 1, x: 0 },
};

const containerVariants: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.03 } },
};

function hourBadge(hour: string | null): { label: string; cls: string } {
  if (hour === "amc") return { label: "AMC", cls: "bg-accent-dim text-accent-strong" };
  if (hour === "bmo") return { label: "BMO", cls: "bg-raised text-ink-secondary" };
  return { label: "—", cls: "" };
}

function statusPill(status: string | null): { label: string; cls: string } | null {
  if (!status) return null;
  const map: Record<string, { label: string; cls: string }> = {
    priced: { label: "Priced", cls: "text-gain" },
    expected: { label: "Expected", cls: "text-accent-strong" },
    filed: { label: "Filed", cls: "text-ink-muted" },
  };
  return map[status] ?? { label: status, cls: "text-ink-muted" };
}

export function IpoCalendar({ listings }: { listings: IpoListing[] }) {
  const navigate = useNavigate();

  const sorted = useMemo(
    () => [...listings].sort((a, b) => (b.date ?? "").localeCompare(a.date ?? "")),
    [listings],
  );

  return (
    <Card className="bg-surface/60 backdrop-blur-sm">
      <CardHeader>
        <CardTitle>IPO calendar</CardTitle>
      </CardHeader>
      <CardContent className="px-2 pb-2 pt-3">
        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.1 }}
          className={cn("overflow-y-auto", sorted.length > MAX_VISIBLE && "max-h-96")}
        >
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr className="text-left text-xs text-ink-muted">
                <th className="px-3 pb-2 font-normal">Date</th>
                <th className="px-3 pb-2 font-normal">Symbol</th>
                <th className="px-3 pb-2 font-normal">Company</th>
                <th className="px-3 pb-2 text-right font-normal">Price</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((ipo, i) => {
                const pill = statusPill(ipo.status);
                return (
                  <motion.tr
                    key={`${ipo.symbol ?? i}-${ipo.date}`}
                    variants={rowVariants}
                    transition={{ duration: 0.35, ease }}
                    className={cn(
                      "border-t border-line/60 transition-colors",
                      ipo.symbol ? "cursor-pointer hover:bg-raised" : "",
                    )}
                    onClick={ipo.symbol ? () => void navigate(`/stocks/${ipo.symbol}`) : undefined}
                  >
                    <td className="num px-3 py-2.5 text-ink-secondary">{ipo.date}</td>
                    <td className="px-3 py-2.5">
                      <span className="num font-semibold">{ipo.symbol ?? "—"}</span>
                      {pill && (
                        <span className={cn("ml-2 text-[11px]", pill.cls)}>
                          {pill.label}
                        </span>
                      )}
                    </td>
                    <td className="max-w-40 truncate px-3 py-2.5 text-ink-secondary">{ipo.name}</td>
                    <td className={cn("num px-3 py-2.5 text-right", ipo.price ? "font-medium" : "text-ink-muted")}>
                      {ipo.price ? `$${ipo.price}` : "—"}
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </motion.div>
      </CardContent>
    </Card>
  );
}

export function EarningsCalendar({ releases }: { releases: EarningsRelease[] }) {
  const navigate = useNavigate();

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
    <Card className="bg-surface/60 backdrop-blur-sm">
      <CardHeader>
        <CardTitle>Earnings calendar</CardTitle>
      </CardHeader>
      <CardContent className="px-2 pb-2 pt-3">
        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.1 }}
          className={cn("overflow-y-auto", sorted.length > MAX_VISIBLE && "max-h-96")}
        >
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr className="text-left text-xs text-ink-muted">
                <th className="px-3 pb-2 font-normal">Date</th>
                <th className="px-3 pb-2 font-normal">Symbol</th>
                <th className="px-3 pb-2 font-normal">When</th>
                <th className="px-3 pb-2 text-right font-normal">EPS est.</th>
                <th className="px-3 pb-2 text-right font-normal">Rev est.</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((e, i) => {
                const badge = hourBadge(e.hour);
                return (
                  <motion.tr
                    key={`${e.symbol}-${i}`}
                    variants={rowVariants}
                    transition={{ duration: 0.35, ease }}
                    className="cursor-pointer border-t border-line/60 transition-colors hover:bg-raised"
                    onClick={() => void navigate(`/stocks/${e.symbol}`)}
                  >
                    <td className="num px-3 py-2.5 text-ink-secondary">{e.date}</td>
                    <td className="num px-3 py-2.5 font-semibold">{e.symbol}</td>
                    <td className="px-3 py-2.5">
                      {badge.label !== "—" ? (
                        <span className={cn("inline-flex rounded-md px-2 py-0.5 text-xs font-medium", badge.cls)}>
                          {badge.label}
                        </span>
                      ) : (
                        <span className="text-ink-muted">—</span>
                      )}
                    </td>
                    <td
                      className={cn(
                        "num px-3 py-2.5 text-right font-medium",
                        e.eps_estimate == null
                          ? "text-ink-muted"
                          : e.eps_estimate >= 0
                            ? "text-gain"
                            : "text-loss",
                      )}
                    >
                      {e.eps_estimate?.toFixed(2) ?? "—"}
                    </td>
                    <td className="num px-3 py-2.5 text-right text-ink-secondary">
                      {e.revenue_estimate_display ?? "—"}
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </motion.div>
      </CardContent>
    </Card>
  );
}
