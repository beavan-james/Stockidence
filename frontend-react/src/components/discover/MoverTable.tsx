import { useNavigate } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Mover } from "@/types/api";
import { cn } from "@/lib/utils";

export function MoverTable({ title, rows }: { title: string; rows: Mover[] }) {
  const navigate = useNavigate();

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="px-2 pb-2 pt-3">
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
              return (
                <tr
                  key={m.ticker}
                  className="cursor-pointer border-t border-line/60 transition-colors hover:bg-raised"
                  onClick={() => void navigate(`/stocks/${m.ticker}`)}
                >
                  <td className="num px-3 py-2.5 font-semibold">{m.ticker}</td>
                  <td className="num px-3 py-2.5 text-right">${m.price}</td>
                  <td className={cn("num px-3 py-2.5 text-right", gain ? "text-gain" : "text-loss")}>
                    {m.change_display ?? m.change_percentage}
                  </td>
                  <td className="num hidden px-3 py-2.5 text-right text-ink-secondary sm:table-cell">
                    {m.volume_display ?? "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
