"use client";

import { Stat, Pnl } from "@/components/stat";
import { cn } from "@/lib/utils";
import { rupees, tone } from "@/lib/format";
import type { OrdersToday, StatusResponse } from "@/lib/types";

export function RiskBar({ status, orders }: { status: StatusResponse | undefined; orders: OrdersToday | undefined }) {
  const risk = status?.risk;
  const limit = risk?.max_daily_loss ?? status?.settings.max_daily_loss ?? 0;
  const dailyPnl = risk?.daily_pnl ?? orders?.summary.realized_pnl ?? 0;
  const used = limit > 0 ? Math.min(1, Math.max(0, -dailyPnl) / limit) : 0;
  const openCount = status?.positions.length ?? 0;
  const maxOpen = risk?.max_open_positions ?? status?.settings.max_open_positions ?? 1;

  return (
    <section aria-label="Risk statistics" className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <Stat
        label="Daily P&L"
        value={<Pnl value={dailyPnl} icon={false} />}
        tone={tone(dailyPnl)}
        sub={risk ? `Realised ${rupees(risk.realized)} · open ${rupees(risk.unrealized)}` : "Realised today"}
      />
      <Stat label="Max drawdown" value={risk ? rupees(risk.max_drawdown) : "—"} tone={risk && risk.max_drawdown > 0 ? "loss" : undefined} sub="Today, peak-to-trough" />
      <Stat label="Orders fired" value={orders?.summary.orders ?? 0} sub={`${orders?.summary.wins ?? 0} wins · ${orders?.summary.losses ?? 0} losses`} />
      <Stat label="Open positions" value={`${openCount} / ${maxOpen}`} sub="Concurrent cap" />
      <div className="col-span-2 min-w-0 rounded-lg border bg-card p-3 md:p-4 lg:col-span-1">
        <p className="label-xs truncate">Daily loss limit</p>
        <p className="num mt-1.5 truncate text-lg font-semibold leading-none md:text-xl">
          {rupees(Math.max(0, -dailyPnl))} <span className="text-sm font-normal text-muted-foreground">/ {rupees(limit)}</span>
        </p>
        <div
          className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(used * 100)}
          aria-label="Share of the daily loss limit used"
        >
          <div className={cn("h-full rounded-full transition-[width] duration-300", used >= 0.8 ? "bg-loss" : used >= 0.5 ? "bg-warn" : "bg-profit")} style={{ width: `${used * 100}%` }} />
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">{risk?.halted ? "Halted — no new entries today" : `${Math.round(used * 100)}% used`}</p>
      </div>
    </section>
  );
}
