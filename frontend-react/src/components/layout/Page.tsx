import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Skeleton } from "@/components/ui/skeleton";
import { QUIET_LINK, cn } from "@/lib/utils";

/**
 * The top of every page: which model or area it belongs to, a link to its
 * sibling page, and one title size site-wide.
 */
export function PageHero({
  eyebrow,
  link,
  title,
  loading = false,
  lede,
  children,
}: {
  eyebrow: string;
  link?: { to: string; label: string } | null;
  title: ReactNode;
  loading?: boolean;
  lede?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="hero-glow pb-14">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 pt-10">
        <p className="text-xs uppercase tracking-[0.14em] text-accent/80">{eyebrow}</p>
        {link && (
          <Link to={link.to} className={QUIET_LINK}>
            {link.label}
          </Link>
        )}
      </div>
      {loading ? (
        <Skeleton className="mt-5 h-40 max-w-3xl" />
      ) : (
        <h1 className="mt-4 max-w-4xl font-medium text-5xl leading-[1.02] tracking-tight sm:text-6xl">{title}</h1>
      )}
      {lede && <p className="mt-6 max-w-2xl text-lg leading-relaxed text-ink-secondary">{lede}</p>}
      {children}
    </section>
  );
}

/** A section under the accent rule. Level 3 is the same block at side-column size. */
export function Section({
  title,
  level = 2,
  aside,
  intro,
  id,
  children,
}: {
  title: ReactNode;
  level?: 2 | 3;
  aside?: ReactNode;
  intro?: ReactNode;
  id?: string;
  children?: ReactNode;
}) {
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <section id={id} className={cn("section-rule scroll-mt-24 pt-6", level === 2 ? "pb-16" : "pb-10")}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <Heading className={cn("font-medium tracking-tight", level === 2 ? "text-4xl" : "text-2xl leading-tight")}>
          {title}
        </Heading>
        {aside}
      </div>
      {intro && (
        <p
          className={cn(
            "leading-relaxed text-ink-secondary",
            level === 2 ? "mt-3 max-w-2xl" : "mt-2 text-sm",
          )}
        >
          {intro}
        </p>
      )}
      {children && <div className="mt-6">{children}</div>}
    </section>
  );
}

/** A figure with its caption beneath. */
export function Stat({ value, label }: { value: ReactNode; label: ReactNode }) {
  return (
    <div>
      <p className="num text-2xl sm:text-3xl">{value}</p>
      <p className="mt-1 text-xs text-ink-muted">{label}</p>
    </div>
  );
}

/** The headline number of a track record. */
export function LeadFigure({ value, unit }: { value: string; unit?: string }) {
  return (
    <p className="num font-medium text-6xl leading-none tracking-tight">
      {value}
      {unit && <span className="text-3xl"> {unit}</span>}
    </p>
  );
}

/** A model's "how it works" steps. */
export function Steps({ steps }: { steps: { title: string; body: string }[] }) {
  return (
    <ol className="grid gap-6 md:grid-cols-2">
      {steps.map((s, i) => (
        <li key={s.title} className="border-t border-line pt-6">
          <span className="num text-sm text-accent">0{i + 1}</span>
          <h3 className="mt-2 font-medium text-2xl">{s.title}</h3>
          <p className="mt-2 text-sm leading-relaxed text-ink-secondary">{s.body}</p>
        </li>
      ))}
    </ol>
  );
}
