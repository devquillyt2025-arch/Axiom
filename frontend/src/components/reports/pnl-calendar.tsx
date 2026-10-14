"use client";

import { useMemo } from "react";
import { compactIN, rupees, signedRupees } from "@/lib/format";
import { cn } from "@/lib/utils";

const DOW = ["M", "T", "W", "T", "F", "S", "S"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const pad = (n: number) => String(n).padStart(2, "0");

interface MonthGrid {
  key: string;
  label: string;
  cells: ({ date: string; day: number } | null)[];
}

function buildMonths(from: string, to: string, cap = 12): MonthGrid[] {
  const [fy, fm] = from.split("-").map(Number);
  const [ty, tm] = to.split("-").map(Number);
  const months: MonthGrid[] = [];
  for (let y = fy, m = fm; y < ty || (y === ty && m <= tm); m === 12 ? (y++, (m = 1)) : m++) {
    const first = new Date(y, m - 1, 1);
    const lead = (first.getDay() + 6) % 7; // Monday-first
    const days = new Date(y, m, 0).getDate();
    const cells: MonthGrid["cells"] = Array(lead).fill(null);
    for (let d = 1; d <= days; d++) cells.push({ date: `${y}-${pad(m)}-${pad(d)}`, day: d });
    months.push({ key: `${y}-${pad(m)}`, label: `${MONTHS[m - 1]} ${y}`, cells });
  }
  return months.slice(-cap);
}

/** Day-wise P&L grid. Cell colour scales with |P&L| relative to the biggest day in range;
 *  the value is also printed (and in the aria-label), so colour is never the only cue. */
export function PnlCalendar({ daily, from, to }: { daily: Record<string, number>; from: string; to: string }) {
  const months = useMemo(() => buildMonths(from, to), [from, to]);
  const maxAbs = useMemo(() => Math.max(1, ...Object.values(daily).map(Math.abs)), [daily]);

  return (
    <div>
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
        {months.map((mo) => {
          const total = mo.cells.reduce((s, c) => s + (c ? (daily[c.date] ?? 0) : 0), 0);
          const traded = mo.cells.some((c) => c && daily[c.date] != null);
          return (
            <div key={mo.key}>
              <div className="mb-2 flex items-baseline justify-between">
                <h3 className="text-[13px] font-medium">{mo.label}</h3>
                {traded && <span className={cn("num text-xs", total >= 0 ? "text-profit" : "text-loss")}>{signedRupees(total)}</span>}
              </div>
              <div className="grid grid-cols-7 gap-1" role="grid" aria-label={`P&L calendar ${mo.label}`}>
                {DOW.map((d, i) => (
                  <div key={i} className="pb-0.5 text-center text-[11px] text-muted-foreground" aria-hidden>
                    {d}
                  </div>
                ))}
                {mo.cells.map((c, i) => {
                  if (!c) return <div key={`b${i}`} />;
                  const v = daily[c.date];
                  const has = v != null;
                  const intensity = has ? 0.18 + 0.62 * (Math.abs(v) / maxAbs) : 0;
                  const label = has ? `${c.date}: ${rupees(v)} ${v >= 0 ? "profit" : "loss"}` : `${c.date}: no trades`;
                  return (
                    <div
                      key={c.date}
                      role="gridcell"
                      aria-label={label}
                      title={label}
                      className={cn(
                        "relative flex aspect-square min-h-9 flex-col justify-between rounded-md border p-1 text-[11px] leading-none",
                        has ? "border-transparent" : "border-border/50 text-muted-foreground/70",
                      )}
                      style={has ? { background: v >= 0 ? `rgba(52,211,153,${intensity})` : `rgba(248,113,113,${intensity})` } : undefined}
                    >
                      <span className={cn("num", has ? "text-foreground/90" : "")}>{c.day}</span>
                      {has && <span className="num hidden text-[11px] font-medium text-foreground sm:block">{v >= 0 ? "+" : "-"}{compactIN(Math.abs(v))}</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground" aria-hidden>
        <span>Loss</span>
        {[0.8, 0.5, 0.25].map((a) => (
          <span key={a} className="size-3.5 rounded-sm" style={{ background: `rgba(248,113,113,${a})` }} />
        ))}
        <span className="size-3.5 rounded-sm border border-border/60" />
        {[0.25, 0.5, 0.8].map((a) => (
          <span key={a} className="size-3.5 rounded-sm" style={{ background: `rgba(52,211,153,${a})` }} />
        ))}
        <span>Profit</span>
      </div>
    </div>
  );
}
