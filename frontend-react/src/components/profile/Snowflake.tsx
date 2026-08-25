import type { CategoryScore } from "@/types/api";
import { categoryColor, categoryLabel } from "@/lib/viz";

const SIZE = 260;
const CENTER = SIZE / 2;
const RADIUS = 82;
const LABEL_RADIUS = 104;

function axisPoint(index: number, total: number, radius: number): [number, number] {
  const angle = (Math.PI * 2 * index) / total - Math.PI / 2;
  return [CENTER + radius * Math.cos(angle), CENTER + radius * Math.sin(angle)];
}

/** Radar of the rated categories — the shape of the thesis at a glance. */
export function Snowflake({ categories }: { categories: CategoryScore[] }) {
  const n = Math.max(categories.length, 3);

  const ring = (fraction: number) =>
    Array.from({ length: n }, (_, i) => axisPoint(i, n, fraction * RADIUS).join(",")).join(" ");

  const polygon = categories
    .map((c, i) => axisPoint(i, n, (Math.max(c.score, 4) / 100) * RADIUS).join(","))
    .join(" ");

  return (
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="h-64 w-64 shrink-0" role="img">
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <polygon key={f} points={ring(f)} fill="none" stroke="#26262b" strokeWidth={1} />
      ))}
      {categories.map((c, i) => {
        const [x, y] = axisPoint(i, n, RADIUS);
        return (
          <line key={c.category} x1={CENTER} y1={CENTER} x2={x} y2={y} stroke="#26262b" />
        );
      })}
      <polygon
        points={polygon}
        fill="rgba(129,140,248,0.14)"
        stroke="#818cf8"
        strokeWidth={2}
        strokeLinejoin="round"
      />
      {categories.map((c, i) => {
        const [x, y] = axisPoint(i, n, (Math.max(c.score, 4) / 100) * RADIUS);
        return <circle key={c.category} cx={x} cy={y} r={3} fill={categoryColor(c.category)} />;
      })}
      {categories.map((c, i) => {
        const [x, y] = axisPoint(i, n, LABEL_RADIUS);
        return (
          <text
            key={c.category}
            x={x}
            y={y}
            textAnchor="middle"
            dominantBaseline="middle"
            style={{ fontSize: 10 }}
            className="fill-zinc-400"
          >
            {categoryLabel(c.category).replace(" (separate)", "")}
          </text>
        );
      })}
    </svg>
  );
}
