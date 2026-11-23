import { useEffect, useRef } from "react";

import { StarField } from "@/lib/starField";

/** A dim pixel starfield fixed behind the page, under everything. */
export function StarBackdrop() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const field = new StarField(canvas);
    return () => field.destroy();
  }, []);

  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <canvas ref={canvasRef} className="pixelated block" />
    </div>
  );
}
