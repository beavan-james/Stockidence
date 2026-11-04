import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Links beside headings and titles: quiet at rest, light blue on hover. */
export const QUIET_LINK = "whitespace-nowrap text-sm text-ink-secondary transition-colors hover:text-accent";

/** Colour of a model's lead or a rank move: accent when positive, muted when not. */
export function leadTone(positive: boolean): string {
  return positive ? "text-accent-strong" : "text-neutral-data";
}
