"use client";

import { useMemo, useState } from "react";
import { Activity, Pause, Play } from "lucide-react";
import { OptionChainTable } from "@/components/analysis/option-chain-table";
import { CandleChart, type Indicators } from "@/components/charts/candle-chart";
import { Segmented, ToggleChip } from "@/components/segmented";
import { Stat } from "@/components/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { C } from "@/lib/chart-theme";
import { compactIN, dateShort, pct, price, tone } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Instrument, LiveSnapshot, OptionChain } from "@/lib/types";

const INTERVALS = [
  { value: 1, label: "1m", days: 2 },
  { value: 3, label: "3m", days: 3 },
  { value: 5, label: "5m", days: 5 },
  { value: 15, label: "15m", days: 10 },
  { value: 30, label: "30m", days: 10 },
  { value: 60, label: "1h", days: 10 },
];

const SYMBOL_LABEL: Record<string, string> = { NIFTY: "Nifty 50", BANKNIFTY: "Bank Nifty", SENSEX: "Sensex", FINNIFTY: "Fin Nifty" };

export default function AnalysisPage() {
  const { data: instruments } = useApi<Instrument[]>("/instruments");
  const [symbol, setSymbol] = useState("NIFTY");
  const [interval, setIntervalMin] = useState(5);
  const [live, setLive] = useState(true);
  const [expiry, setExpiry] = useState<string | null>(null);
  const [show, setShow] = useState<Indicators>({ ema9: true, ema21: true, ema50: false, bb: false, rsi: false, macd: false });
  const toggle = (k: keyof Indicators) => setShow((s) => ({ ...s, [k]: !s[k] }));

  const days = INTERVALS.find((i) => i.value === interval)?.days ?? 5;
  const { data: snap, error: snapErr } = useApi<LiveSnapshot>(`/market/live?symbol=${symbol}&interval=${interval}&days=${days}`, {
    refreshInterval: live ? 5000 : 0,
  });
  const { data: chain, error: chainErr } = useApi<OptionChain>(`/market/optionchain?symbol=${symbol}${expiry ? `&expiry=${expiry}` : ""}&width=12`, {
    refreshInterval: live ? 10000 : 0,
  });

  const options = useMemo(
    () => (instruments ?? Object.keys(SYMBOL_LABEL).map((s) => ({ symbol: s }))).map((i) => ({ value: i.symbol, label: SYMBOL_LABEL[i.symbol] ?? i.symbol })),
    [instruments],
  );
  const mood = chain?.mood;
  const moodVariant = mood?.label === "Bullish" ? "profit" : mood?.label === "Bearish" ? "loss" : "muted";

  const onSymbol = (s: string) => {
    setSymbol(s);
    setExpiry(null); // expiries differ per underlying
  };

  return (
    <div className="space-y-4 md:space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Analysis</h1>
        <div className="flex flex-wrap items-center gap-2">
          {snap && !snap.market_open && <Badge variant="muted">Market closed · last session {dateShort(snap.session_date)}</Badge>}
          {snap?.source === "demo" && <Badge variant="warn">Demo data</Badge>}
          <Button variant="outline" size="sm" onClick={() => setLive((v) => !v)} aria-pressed={live}>
            {live ? <Pause /> : <Play />} {live ? "Pause updates" : "Resume updates"}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Segmented label="Instrument" value={symbol} onChange={onSymbol} options={options} />
        <div className="w-24">
          <Select value={String(interval)} onValueChange={(v) => setIntervalMin(Number(v))}>
            <SelectTrigger aria-label="Candle timeframe">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {INTERVALS.map((i) => (
                <SelectItem key={i.value} value={String(i.value)}>
                  {i.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {(snapErr || chainErr) && <Alert variant="error" title="Market data unavailable">{(snapErr ?? chainErr)?.message}</Alert>}

      <section aria-label="Quote summary" className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {snap ? (
          <>
            <Stat className="col-span-2 md:col-span-1" label={`${snap.name} LTP`} value={price(snap.ltp)} tone={tone(snap.change)} sub={`${snap.change >= 0 ? "+" : ""}${price(snap.change)} (${pct(snap.change_pct, 2, true)})`} />
            <Stat label="Day open" value={price(snap.ohlc.open)} />
            <Stat label="Day high" value={price(snap.ohlc.high)} />
            <Stat label="Day low" value={price(snap.ohlc.low)} />
            <Stat label="India VIX" value={snap.vix != null ? snap.vix.toFixed(2) : "—"} sub="Volatility index" />
            <Stat label="Volume" value={compactIN(snap.ohlc.volume)} sub={`Prev close ${price(snap.prev_close)}`} />
          </>
        ) : (
          // same markup as the real tiles, so nothing below jumps when the numbers arrive
          Array.from({ length: 6 }).map((_, i) => <Stat key={i} loading label="Loading" value="0" sub="Loading" className={i === 0 ? "col-span-2 md:col-span-1" : undefined} />)
        )}
      </section>

      <Card>
        <CardHeader className="gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Activity className="size-4 text-muted-foreground" aria-hidden /> {snap?.name ?? SYMBOL_LABEL[symbol]} · {INTERVALS.find((i) => i.value === interval)?.label}
              </CardTitle>
              <CardDescription>Times shown in IST. Toggle overlays below; RSI and MACD open in their own panes.</CardDescription>
            </div>
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Indicator overlays">
            <ToggleChip pressed={show.ema9} onToggle={() => toggle("ema9")} swatch={C.ema9}>EMA 9</ToggleChip>
            <ToggleChip pressed={show.ema21} onToggle={() => toggle("ema21")} swatch={C.ema21}>EMA 21</ToggleChip>
            <ToggleChip pressed={show.ema50} onToggle={() => toggle("ema50")} swatch={C.ema50}>EMA 50</ToggleChip>
            <ToggleChip pressed={show.bb} onToggle={() => toggle("bb")} swatch={C.bb}>Bollinger</ToggleChip>
            <ToggleChip pressed={show.rsi} onToggle={() => toggle("rsi")} swatch={C.rsi}>RSI 14</ToggleChip>
            <ToggleChip pressed={show.macd} onToggle={() => toggle("macd")} swatch={C.macd}>MACD</ToggleChip>
          </div>
        </CardHeader>
        <CardContent>
          {snap ? (
            <CandleChart
              candles={snap.candles}
              show={show}
              resetKey={`${snap.symbol}-${snap.interval}`}
              ariaLabel={`${snap.name} ${snap.interval}-minute candlestick chart. Last price ${price(snap.ltp)}, ${pct(snap.change_pct, 2, true)} on the day.`}
            />
          ) : (
            // 340/440px chart + the 28px price-legend row the real chart renders above it
            <Skeleton className="h-[368px] md:h-[468px]" />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="gap-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>Option chain</CardTitle>
              <CardDescription>
                {chain ? `Spot ${price(chain.spot)} · ATM ${chain.atm.toLocaleString("en-IN")}` : "Loading…"} · shaded bars show open interest; PCR = put OI ÷ call OI.
              </CardDescription>
            </div>
            <div className="w-44">
              <Select value={chain?.expiry ?? ""} onValueChange={setExpiry}>
                <SelectTrigger aria-label="Expiry date">
                  <SelectValue placeholder="Expiry" />
                </SelectTrigger>
                <SelectContent>
                  {(chain?.expiries ?? []).map((e) => (
                    <SelectItem key={e} value={e}>
                      {dateShort(e)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          {chain && mood && (
            <div className="grid gap-3 lg:grid-cols-[auto_1fr]">
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border bg-muted/30 p-3">
                <div>
                  <p className="label-xs">Market mood</p>
                  <Badge variant={moodVariant} className="mt-1 h-7 px-3 text-sm">
                    {mood.label}
                  </Badge>
                </div>
                <div>
                  <p className="label-xs">Total PCR</p>
                  <p className="num mt-1 text-base font-semibold">{chain.pcr != null ? chain.pcr.toFixed(2) : "—"}</p>
                </div>
                <div>
                  <p className="label-xs">Max pain</p>
                  <p className="num mt-1 text-base font-semibold">{chain.max_pain?.toLocaleString("en-IN") ?? "—"}</p>
                </div>
                <div>
                  <p className="label-xs">Support (max put OI)</p>
                  <p className="num mt-1 text-base font-semibold text-profit">{chain.support?.toLocaleString("en-IN") ?? "—"}</p>
                </div>
                <div>
                  <p className="label-xs">Resistance (max call OI)</p>
                  <p className="num mt-1 text-base font-semibold text-loss">{chain.resistance?.toLocaleString("en-IN") ?? "—"}</p>
                </div>
              </div>
              <ul className="space-y-1 self-center text-[13px] text-muted-foreground">
                {mood.reasons.map((r) => (
                  <li key={r} className="flex gap-2">
                    <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground/60" />
                    {r}
                  </li>
                ))}
                <li className="text-xs text-muted-foreground/70">A rule-of-thumb read from PCR + VIX, not a prediction.</li>
              </ul>
            </div>
          )}
        </CardHeader>
        <CardContent className="px-0 md:px-0">{chain ? <OptionChainTable chain={chain} /> : <div className="px-4"><Skeleton className="h-64" /></div>}</CardContent>
      </Card>
    </div>
  );
}
