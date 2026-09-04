import { useNavigate } from "react-router-dom";
import { motion, type Variants } from "framer-motion";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Mover } from "@/types/api";
import { cn } from "@/lib/utils";

const ease = [0.22, 1, 0.36, 1] as const;

const rowVariants: Variants = {
  hidden: { opacity: 0, x: -6 },
  visible: { opacity: 1, x: 0 },
};

const containerVariants: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.03 } },
};

export function MoverTable({ title, rows }: { title: string; rows: Mover[] }) {
  const navigate = useNavigate();

  return (
    <Card className="bg-surface/60 backdrop-blur-sm">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="px-2 pb-2 pt-3">
        <motion.div variants={containerVariants} initial="hidden" whileInView="visible" viewport={{ once: true, amount: 0.1 }}>
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
                  <motion.tr
                    key={m.ticker}
                    variants={rowVariants}
                    transition={{ duration: 0.35, ease }}
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
