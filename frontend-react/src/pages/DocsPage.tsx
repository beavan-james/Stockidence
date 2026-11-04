import { useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { PageHero } from "@/components/layout/Page";
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
    document.title = "Documentation | Stockidence";
  }, []);

  return (
    <div>
      <PageHero
        eyebrow="Documentation"
        title={
          <>
            How Stockidence <em className="not-italic text-accent">is built.</em>
          </>
        }
        lede="The pipeline, the ranking models and the data sources, from the write-ups in the repo."
      />

      <div className="flex gap-10">
        <nav className="sticky top-24 hidden w-44 shrink-0 self-start text-sm md:block">
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className={`block border-l py-1.5 pl-3 transition-colors ${
                activeId === s.id ? "border-accent text-accent" : "border-line text-ink-secondary hover:text-accent"
              }`}
            >
              {s.label}
            </a>
          ))}
        </nav>

        <div className="min-w-0 flex-1">
          {SECTIONS.map((s) => (
            <section key={s.id} id={s.id} className="section-rule scroll-mt-24 pb-16 pt-6">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                {s.content}
              </ReactMarkdown>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
