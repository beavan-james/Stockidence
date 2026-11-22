import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** The page column: header, footer and every page's content share it. */
export const CONTAINER = "mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-12";

/** Links beside headings and titles: quiet at rest, orange on hover. */
export const QUIET_LINK = "whitespace-nowrap text-sm text-ink-secondary transition-colors hover:text-accent";

/** Colour of a model's lead or a rank move: accent when positive, muted when not. */
export function leadTone(positive: boolean): string {
  return positive ? "text-accent-strong" : "text-neutral-data";
}
