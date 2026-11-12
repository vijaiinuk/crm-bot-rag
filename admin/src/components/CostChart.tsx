import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { CostSummary } from "../api/types";
import { money } from "../format";

const SERIES = [
  { key: "chat", name: "Chat (clients)", color: "var(--series-chat)" },
  { key: "eval", name: "Evals", color: "var(--series-eval)" },
  { key: "ingest", name: "Ingest", color: "var(--series-ingest)" },
] as const;

const shortDay = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });

/** Stacked daily cost by bucket. */
export function CostChart({ daily }: { daily: CostSummary["daily"] }) {
  const rows = daily.map((d) => ({ ...d, label: shortDay.format(new Date(d.date)) }));
  return (
    <div className="chart" role="img" aria-label="Daily estimated LLM cost by bucket">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "var(--line)" }} minTickGap={16} />
          <YAxis tick={{ fill: "var(--muted)", fontSize: 11 }} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => money(v)} />
          <Tooltip
            formatter={(v) => money(Number(v))}
            contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 8, color: "var(--ink)" }}
            cursor={{ fill: "var(--accent-soft)" }}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} />
          {SERIES.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.name} stackId="cost" fill={s.color} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
