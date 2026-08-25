import { useCountUp } from "@/hooks/useCountUp";
import { cn } from "@/lib/utils";

interface AnimatedNumberProps {
  value: number;
  decimals?: number;
  format?: (value: number) => string;
  className?: string;
}

/** A figure that counts up to its value on mount/update. */
export function AnimatedNumber({ value, decimals = 1, format, className }: AnimatedNumberProps) {
  const display = useCountUp(value);
  const text = format ? format(display) : display.toFixed(decimals);
  return (
    <span className={cn("num", className)} title={format ? format(value) : value.toFixed(decimals)}>
      {text}
    </span>
  );
}
