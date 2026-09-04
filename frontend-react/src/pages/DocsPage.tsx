import { useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { useActiveSection } from "@/hooks/useActiveSection";
import { mdComponents } from "@/components/markdown";
import readme from "../../../README.md?raw";
import architecture from "../../../ARCHITECTURE.md?raw";
import model from "../../../TICKER_STATS.md?raw";
import api from "../../../API.md?raw";
import rankingModel from "../../../Model/README.md?raw";

const SECTIONS = [
  { id: "readme", label: "Overview", content: readme },
  { id: "architecture", label: "Architecture", content: architecture },
  { id: "model", label: "Ticker Stats", content: model },
  { id: "ranking-model", label: "Ranking Model", content: rankingModel },
  { id: "api", label: "APIs Used", content: api },
] as const;

export function DocsPage() {
  const ids = SECTIONS.map((s) => s.id);
  const activeId = useActiveSection(ids);

  useEffect(() => {
    document.title = "Documentation — Stockidence";
  }, []);

  return (
    <div className="flex gap-10">
      <nav className="sticky top-24 hidden w-44 shrink-0 space-y-1 self-start text-sm md:block">
        {SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className={`block rounded-lg px-3 py-1.5 transition-colors ${
              activeId === s.id
                ? "bg-accent/10 font-medium text-accent"
                : "text-ink-secondary hover:bg-raised hover:text-ink"
            }`}
          >
            {s.label}
          </a>
        ))}
      </nav>

      <div className="min-w-0 flex-1 space-y-16">
        {SECTIONS.map((s) => (
          <section key={s.id} id={s.id} className="scroll-mt-24">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {s.content}
            </ReactMarkdown>
          </section>
        ))}
      </div>
    </div>
  );
}
