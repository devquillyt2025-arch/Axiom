"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Activity, Radio } from "lucide-react";
import { BotControls } from "@/components/bot/bot-controls";
import { BotLogs, OrdersLog } from "@/components/bot/orders-log";
import { PositionsTable } from "@/components/bot/positions-table";
import { RiskBar } from "@/components/bot/risk-bar";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useApi, useStatus } from "@/lib/hooks";
import { price } from "@/lib/format";
import type { BotStatusName, OrdersToday } from "@/lib/types";

const statusMeta: Record<BotStatusName, { label: string; variant: "profit" | "warn" | "loss" | "muted" | "default" }> = {
  idle: { label: "Idle", variant: "muted" },
  starting: { label: "Starting", variant: "default" },
  waiting: { label: "Waiting for market", variant: "warn" },
  running: { label: "Running", variant: "profit" },
  stopping: { label: "Stopping", variant: "warn" },
  stopped: { label: "Stopped", variant: "muted" },
  error: { label: "Error", variant: "loss" },
  crashed: { label: "Not responding", variant: "loss" },
};

/** Reads ?auth=ok|error from the Upstox OAuth callback redirect, shows it once, then cleans the URL. */
function AuthResult() {
  const params = useSearchParams();
  const router = useRouter();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    const a = params.get("auth");
    if (!a) return;
    setMsg(a === "ok" ? { ok: true, text: "Upstox connected. Live data is now flowing." } : { ok: false, text: params.get("reason") || "Upstox login failed." });
    router.replace("/bot");
  }, [params, router]);
  if (!msg) return null;
  return msg.ok ? <Alert variant="success">{msg.text}</Alert> : <Alert variant="error" title="Upstox login didn't complete">{msg.text}</Alert>;
}

export default function BotPage() {
  const { data: status } = useStatus(2000);
  const { data: orders, isLoading } = useApi<OrdersToday>("/orders/today", { refreshInterval: 3000 });
  const bot = status?.bot;
  const meta = statusMeta[bot?.status ?? "idle"];
  const live = bot?.mode === "live";

  return (
    <div className="space-y-4 md:space-y-5">
      <Suspense fallback={null}>
        <AuthResult />
      </Suspense>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Bot</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={meta.variant} className="h-7 px-2.5 text-[13px]">
            {bot?.status === "running" && <span className="size-1.5 animate-pulse-dot rounded-full bg-profit" aria-hidden />}
            {meta.label}
          </Badge>
          {bot?.mode && <Badge variant={live ? "live" : "warn"} className="h-7 px-2.5 text-[13px]">{live ? "LIVE" : "PAPER"}</Badge>}
        </div>
      </div>

      {live && bot?.running && (
        <Alert variant="error" title="LIVE mode — real orders are being placed">
          Stops are managed by the bot, not the exchange. Keep this machine and its internet connection up while positions are open.
        </Alert>
      )}
      {bot?.message && bot.status !== "running" && (
        <Alert variant={bot.status === "error" || bot.status === "crashed" ? "error" : "info"}>{bot.message}</Alert>
      )}
      {status?.risk?.halted && <Alert variant="warn" title="Risk halt">{status.risk.halt_reason}</Alert>}

      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-3 p-4 md:p-5">
          <div className="flex items-center gap-2.5">
            <Activity className="size-4 text-muted-foreground" aria-hidden />
            <div>
              <p className="label-xs">Active strategy</p>
              <p className="text-sm font-medium">
                {bot?.strategy_name && bot.status !== "idle" ? (
                  <>
                    {bot.strategy_name} <span className="text-muted-foreground">· {bot.symbol} · {bot.lots} lot{(bot.lots ?? 1) > 1 ? "s" : ""}</span>
                  </>
                ) : (
                  <span className="text-muted-foreground">None — bot isn&apos;t running</span>
                )}
              </p>
            </div>
          </div>
          {bot?.spot != null && (
            <div>
              <p className="label-xs">Spot / VIX</p>
              <p className="num text-sm font-medium">
                {price(bot.spot)} <span className="text-muted-foreground">/ {bot.vix != null ? bot.vix.toFixed(2) : "—"}</span>
              </p>
            </div>
          )}
          {bot?.last_signal && (
            <div className="min-w-0">
              <p className="label-xs">Last signal</p>
              <p className="truncate text-sm font-medium">
                <span className={bot.last_signal.direction === "BULLISH" ? "text-profit" : "text-loss"}>{bot.last_signal.direction}</span>{" "}
                <span className="text-muted-foreground">{bot.last_signal.reason}</span>
              </p>
            </div>
          )}
          {bot?.running && (
            <div className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
              <Radio className="size-3.5" aria-hidden />
              {bot.feed_connected ? "WebSocket feed" : "REST price polling"}
            </div>
          )}
        </CardContent>
      </Card>

      <RiskBar status={status} orders={orders} />
      <BotControls status={status} />
      <PositionsTable positions={status?.positions ?? []} unmanaged={bot?.status === "crashed"} />
      <div className="grid grid-cols-1 gap-4 md:gap-5 xl:grid-cols-5">
        <div className="min-w-0 xl:col-span-3">
          <OrdersLog data={orders} loading={isLoading} />
        </div>
        <div className="min-w-0 xl:col-span-2">
          <BotLogs logs={status?.logs ?? []} />
        </div>
      </div>
    </div>
  );
}
