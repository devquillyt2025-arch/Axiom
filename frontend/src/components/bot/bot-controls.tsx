"use client";

import { useEffect, useMemo, useState } from "react";
import { useSWRConfig } from "swr";
import { Play, ShieldAlert, Square } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ParamFields, defaultsFor, type ParamValues } from "@/components/param-fields";
import { Segmented } from "@/components/segmented";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Instrument, StatusResponse, StrategyInfo } from "@/lib/types";

export function BotControls({ status }: { status: StatusResponse | undefined }) {
  const { mutate } = useSWRConfig();
  const { data: strategies } = useApi<StrategyInfo[]>("/strategies");
  const { data: instruments } = useApi<Instrument[]>("/instruments");

  const [strategyKey, setStrategyKey] = useState("ema_crossover");
  const [symbol, setSymbol] = useState("NIFTY");
  const [lots, setLots] = useState(1);
  const [paper, setPaper] = useState(true);
  const [liveConfirmed, setLiveConfirmed] = useState(false);
  const [params, setParams] = useState<ParamValues>({});
  const [busy, setBusy] = useState<"start" | "stop" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [typed, setTyped] = useState("");

  const bot = status?.bot;
  const running = !!bot?.running;
  const stopping = bot?.status === "stopping";
  const maxLots = status?.settings.max_lots ?? 1;
  const strategy = useMemo(() => strategies?.find((s) => s.key === strategyKey), [strategies, strategyKey]);

  // adopt the server's PAPER_TRADE default once
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    if (status && !seeded) {
      setPaper(status.settings.paper_default);
      setSeeded(true);
    }
  }, [status, seeded]);

  // reset parameter fields to the strategy's defaults when the strategy changes
  useEffect(() => {
    if (strategy) setParams(defaultsFor(strategy.params));
  }, [strategy]);

  const onPaperChange = (checked: boolean) => {
    if (checked) {
      setPaper(true);
      setLiveConfirmed(false);
    } else {
      setTyped("");
      setDialogOpen(true); // live mode needs a typed confirmation
    }
  };

  const start = async () => {
    setBusy("start");
    setError(null);
    setNotice(null);
    try {
      const body = { strategy: strategyKey, symbol, lots, paper, params, confirm_live: !paper && liveConfirmed };
      const r = await api.post<{ mode: string; lots: number }>("/bot/start", body);
      setNotice(`Bot started in ${r.mode.toUpperCase()} mode with ${r.lots} lot${r.lots > 1 ? "s" : ""}.`);
      await mutate("/status");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const stop = async () => {
    setBusy("stop");
    setError(null);
    try {
      const r = await api.post<{ detail: string }>("/bot/stop");
      setNotice(r.detail);
      await mutate("/status");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const locked = running || stopping;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="space-y-1">
          <CardTitle>Controls</CardTitle>
          <CardDescription>
            {locked ? "Stop the bot to change its configuration." : "Pick a strategy from the registry, size it, and start. Paper mode is the default."}
          </CardDescription>
        </div>
        {locked ? (
          <Button variant="destructive" onClick={stop} loading={busy === "stop" || stopping} disabled={stopping}>
            <Square /> {stopping ? "Stopping…" : "Stop bot"}
          </Button>
        ) : (
          <Button
            onClick={start}
            loading={busy === "start"}
            disabled={!strategy || !status?.auth.authenticated}
            variant={paper ? "default" : "destructive"}
            title={!status?.auth.authenticated ? "Connect Upstox first — the bot needs live market data even in paper mode" : undefined}
          >
            <Play /> {paper ? "Start paper bot" : "Start LIVE bot"}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {!locked && !status?.auth.authenticated && (
          <Alert variant="info">Connect Upstox to start the bot — it needs real market data even in paper mode.</Alert>
        )}
        {error && <Alert variant="error" title="Couldn't complete that">{error}</Alert>}
        {notice && !error && <Alert variant="success">{notice}</Alert>}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="bot-strategy">Strategy</Label>
            <Select value={strategyKey} onValueChange={setStrategyKey} disabled={locked}>
              <SelectTrigger id="bot-strategy">
                <SelectValue placeholder="Loading…" />
              </SelectTrigger>
              <SelectContent>
                {strategies?.map((s) => (
                  <SelectItem key={s.key} value={s.key}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label id="bot-symbol-label">Instrument</Label>
            <Segmented
              label="Instrument"
              value={symbol}
              onChange={setSymbol}
              disabled={locked}
              options={(instruments ?? [{ symbol: "NIFTY", name: "Nifty 50" }]).map((i) => ({ value: i.symbol, label: i.symbol === "NIFTY" ? "Nifty" : i.name }))}
              className="w-full [&>button]:flex-1"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="bot-lots">Lots (max {maxLots})</Label>
            <Input
              id="bot-lots"
              type="number"
              inputMode="numeric"
              min={1}
              max={maxLots}
              value={lots}
              disabled={locked}
              onChange={(e) => setLots(Math.max(1, Math.min(maxLots, Number(e.target.value) || 1)))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="bot-paper">Trading mode</Label>
            <div className="flex h-11 items-center justify-between gap-3 rounded-md border border-input bg-muted/40 px-3 md:h-9">
              <div className="flex items-center gap-2">
                <Badge variant={paper ? "warn" : "live"}>{paper ? "PAPER" : "LIVE"}</Badge>
                <span className="text-xs text-muted-foreground">{paper ? "Simulated fills" : "Real orders"}</span>
              </div>
              <Switch id="bot-paper" checked={paper} onCheckedChange={onPaperChange} disabled={locked} aria-label="Paper trading mode" />
            </div>
          </div>
        </div>

        {strategy && (
          <div className="space-y-3 border-t pt-4">
            <p className="text-[13px] text-muted-foreground">{strategy.description}</p>
            <ParamFields params={strategy.params} values={params} onChange={setParams} disabled={locked} idPrefix="bot" />
          </div>
        )}
      </CardContent>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert className="size-5 text-loss" aria-hidden /> Switch to LIVE trading?
            </DialogTitle>
            <DialogDescription>The bot will place real orders in your Upstox account with real money.</DialogDescription>
          </DialogHeader>
          <ul className="list-disc space-y-1.5 pl-5 text-[13px] text-muted-foreground">
            <li>Selling options can lose far more than the premium collected.</li>
            <li>
              Stops are managed by the bot, <b className="text-foreground">not placed at the exchange</b>. If the bot, this PC or your internet fails, open positions are unprotected.
            </li>
            <li>Upstox requires a registered static IP for API orders. Orders are LIMIT orders (market orders are no longer accepted).</li>
            <li>Run paper mode first, then go live with 1 lot and watch the Upstox order book.</li>
          </ul>
          <div className="space-y-1.5">
            <Label htmlFor="live-confirm">
              Type <b className="text-foreground">LIVE</b> to confirm
            </Label>
            <Input id="live-confirm" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" autoCapitalize="characters" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              Stay in paper mode
            </Button>
            <Button
              variant="destructive"
              disabled={typed.trim() !== "LIVE"}
              onClick={() => {
                setPaper(false);
                setLiveConfirmed(true);
                setDialogOpen(false);
              }}
            >
              Enable live mode
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
