import type { InputHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-9 w-full rounded-lg border border-line bg-transparent px-3 text-sm text-ink placeholder:text-ink-muted",
        "focus:border-accent/50 focus:outline-none",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
