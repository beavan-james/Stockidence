import type { InputHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-[10px] border border-white/[0.16] bg-black/55 px-3.5 text-sm text-ink placeholder:text-ink-muted",
        "transition-colors focus:border-accent focus:outline-none",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
