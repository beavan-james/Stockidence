import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("sk-shimmer rounded-lg bg-raised", className)} {...props} />;
}

export { Skeleton };
