"use client";

import { useEffect, useMemo, useState } from "react";
import { useSWRConfig } from "swr";
import { FlaskConical, History } from "lucide-react";
import { EquityChart } from "@/components/charts/equity-chart";
import { ParamFields, defaultsFor, type ParamValues } from "@/components/param-fields";
import { Segmented } from "@/components/segmented";
import { EmptyState, Pnl, Stat } from "@/components/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, errorMessage } from "@/lib/api";
import { daysAgo, formatDuration, isoDate, pct, price, rupees, dateShort, timeIST, tone } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { BacktestListItem, BacktestRequest, BacktestResult, Instrument, StrategyInfo } from "@/lib/types";

const PRESETS = [
  { label: "1M", days: 30 },
  { label: "3M", days: 91 },
  { label: "6M", days: 182 },
  { label: "1Y", days: 365 },
];
const PAGE = 25;

export default function BacktestPage() {
  const { mutate } = useSWRConfig();
  const { data: strategies } = useApi<StrategyInfo[]>("/strategies");
  const { data: instruments } = useApi<Instrument[]>("/instruments");
  const { data: saved } = useApi<{ results: BacktestListItem[] }>("/backtest/results");

  const [strategyKey, setStrategyKey] = useState("ema_crossover");
  const [symbol, setSymbol] = useState("NIFTY");
  const [start, setStart] = useState(daysAgo(91));
  const [end, setEnd] = useState(isoDate(new Date()));
  const [capital, setCapital] = useState(200000);
  const [lots, setLots] = useState(1);
  const [lotSize, setLotSize] = useState<string>("");
  const [slippage, setSlippage] = useState(0.5);
  const [charges, setCharges] = useState(40);
  const [params, setParams] = useState<ParamValues>({});
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [shown, setShown] = useState(PAGE);

  const strategy = useMemo(() => strategies?.find((s) => s.key === strategyKey), [strategies, strategyKey]);
  const defaultLot = instruments?.find((i) => i.symbol === symbol)?.lot_size;
  useEffect(() => {
    if (strategy) setParams(defaultsFor(strategy.params));
  }, [strategy]);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const body: BacktestRequest = {
        strategy: strategyKey, symbol, start, end, capital, lots,
        lot_size: lotSize ? Number(lotSize) : null, slippage, charges_per_order: charges, params,
      };
      const r = await api.post<BacktestResult>("/backtest", body);
      setResult(r);
      setShown(PAGE);
      if (r.id) mutate("/backtest/results");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setRunning(false);
    }
  };

  const loadSaved = async (id: string) => {
    setError(null);
    try {
      setResult(await api.get<BacktestResult>(`/backtest/results/${id}`));
      setShown(PAGE);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const m = result?.metrics;
  return (
    <div className="space-y-4 md:space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Backtesting</h1>
        {saved && saved.results.length > 0 && (
          <div className="w-full sm:w-72">
            <Select onValueChange={loadSaved}>
              <SelectTrigger aria-label="Load a saved backtest">
                <History className="size-4 shrink-0 opacity-70" aria-hidden />
                <SelectValue placeholder="Load a saved run…" />
              </SelectTrigger>
              <SelectContent>
                {saved.results.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.strategy} · {s.instrument} · {pct(s.metrics.return_pct, 1, true)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Setup</CardTitle>
          <CardDescription>Strategies come from the Python registry (backend/strategies). Each signal sells (or buys) the at-the-money option.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="space-y-1.5">
              <Label htmlFor="bt-strategy">Strategy</Label>
              <Select value={strategyKey} onValueChange={setStrategyKey}>
                <SelectTrigger id="bt-strategy">
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
            <div className="space-y-1.5 md:col-span-1 xl:col-span-3">
              <Label>Instrument</Label>
              <Segmented
                label="Instrument"
                value={symbol}
                onChange={setSymbol}
                options={(instruments ?? [{ symbol: "NIFTY", name: "Nifty 50" }]).map((i) => ({ value: i.symbol, label: i.name }))}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            <div className="space-y-1.5">
              <Label htmlFor="bt-start">Start date</Label>
              <Input id="bt-start" type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="bt-end">End date</Label>
              <Input id="bt-end" type="date" value={end} min={start} max={isoDate(new Date())} onChange={(e) => setEnd(e.target.value)} />
            </div>
            <div className="col-span-2 flex items-end gap-2 md:col-span-1 xl:col-span-2">
              {PRESETS.map((p) => (
                <Button key={p.label} type="button" variant="outline" size="sm" onClick={() => { setStart(daysAgo(p.days)); setEnd(isoDate(new Date())); }}>
                  {p.label}
                </Button>
              ))}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="bt-capital">Capital (₹)</Label>
              <Input id="bt-capital" type="number" inputMode="numeric" min={1000} step={10000} value={capital} onChange={(e) => setCapital(Number(e.target.value))} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="bt-lots">Lots</Label>
              <Input id="bt-lots" type="number" inputMode="numeric" min={1} max={100} value={lots} onChange={(e) => setLots(Math.max(1, Number(e.target.value) || 1))} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="bt-lotsize">Lot size</Label>
              <Input id="bt-lotsize" type="number" inputMode="numeric" min={1} placeholder={defaultLot ? `default ${defaultLot}` : ""} value={lotSize} onChange={(e) => setLotSize(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="bt-slip">Slippage (₹/unit/side)</Label>
              <Input id="bt-slip" type="number" inputMode="decimal" min={0} step={0.05} value={slippage} onChange={(e) => setSlippage(Number(e.target.value))} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="bt-charges">Charges (₹/order)</Label>
              <Input id="bt-charges" type="number" inputMode="decimal" min={0} step={5} value={charges} onChange={(e) => setCharges(Number(e.target.value))} />
            </div>
          </div>

          {strategy && (
            <div className="space-y-3 border-t pt-4">
              <p className="text-[13px] text-muted-foreground">{strategy.description}</p>
              <ParamFields params={strategy.params} values={params} onChange={setParams} idPrefix="bt" />
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button size="lg" onClick={run} loading={running} disabled={!strategy || start >= end}>
              <FlaskConical /> {running ? "Running…" : "Run backtest"}
            </Button>
            {running && <p className="text-[13px] text-muted-foreground">Fetching candles and simulating — long ranges on 1–3 minute bars can take a while.</p>}
          </div>
          {error && <Alert variant="error" title="Backtest failed">{error}</Alert>}
        </CardContent>
      </Card>

      {!result && !running && (
        <Card>
          <EmptyState icon={<FlaskConical />} title="No results yet">
            Configure a strategy and run a backtest. Results include the equity curve, risk metrics and every simulated trade.
          </EmptyState>
        </Card>
      )}

      {result && m && (
        <>
          {result.data_source === "demo" && (
            <Alert variant="warn" title="These results use synthetic demo data">
              Connect Upstox to backtest on real index history. Demo runs aren&apos;t saved.
            </Alert>
          )}
          <Alert variant="info" title="How to read this">
            {result.model}
          </Alert>

          <section aria-label="Backtest metrics" className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Total P&L" value={<Pnl value={m.total_pnl} icon={false} />} tone={tone(m.total_pnl)} sub={`${pct(m.return_pct, 1, true)} on ${rupees(result.config.capital)}`} />
            <Stat label="Win rate" value={m.win_rate != null ? `${m.win_rate}%` : "—"} sub={`${m.total_trades} trades`} />
            <Stat label="Max drawdown" value={rupees(m.max_drawdown)} tone={m.max_drawdown > 0 ? "loss" : undefined} sub={`${m.max_drawdown_pct}% of peak equity`} />
            <Stat label="Sharpe ratio" value={m.sharpe != null ? m.sharpe.toFixed(2) : "—"} sub="Daily, annualised, rf = 0" />
            <Stat label="Total trades" value={m.total_trades} sub={`${m.trading_days} trading days`} />
            <Stat label="Avg profit" value={m.avg_profit != null ? <Pnl value={m.avg_profit} icon={false} /> : "—"} tone={m.avg_profit != null ? "profit" : undefined} sub="Per winning trade" />
            <Stat label="Avg loss" value={m.avg_loss != null ? <Pnl value={m.avg_loss} icon={false} /> : "—"} tone={m.avg_loss != null ? "loss" : undefined} sub="Per losing trade" />
            <Stat label="R : R ratio" value={m.rr_ratio != null ? `1 : ${m.rr_ratio}` : "—"} sub={m.profit_factor != null ? `Profit factor ${m.profit_factor}` : "Avg profit ÷ avg loss"} />
          </section>

          <Card>
            <CardHeader>
              <CardTitle>Equity curve</CardTitle>
              <CardDescription>
                {result.config.strategy_name ?? result.config.strategy} · {result.config.symbol} · {dateShort(result.config.start)} → {dateShort(result.config.end)} · {result.config.lots} lot × {result.config.lot_size}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <EquityChart
                data={result.equity}
                baseValue={result.config.capital}
                ariaLabel={`Equity curve from ${rupees(result.config.capital)} to ${rupees(m.final_equity)} over ${m.trading_days} trading days.`}
              />
              <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-[13px] sm:grid-cols-4">
                {[
                  ["Final equity", rupees(m.final_equity)],
                  ["Expectancy / trade", m.expectancy != null ? rupees(m.expectancy) : "—"],
                  ["Best day", m.best_day != null ? rupees(m.best_day) : "—"],
                  ["Worst day", m.worst_day != null ? rupees(m.worst_day) : "—"],
                ].map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-xs text-muted-foreground">{k}</dt>
                    <dd className="num font-medium">{v}</dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Trades ({result.trades.length})</CardTitle>
              <span className="text-xs text-muted-foreground">Avg duration {formatDuration(m.avg_duration_min)}</span>
            </CardHeader>
            <CardContent className="px-0 md:px-0">
              {result.trades.length === 0 ? (
                <EmptyState title="The strategy never triggered in this range">Try a longer range, a shorter timeframe, or looser parameters.</EmptyState>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead>#</TableHead>
                        <TableHead>Date</TableHead>
                        <TableHead>Instrument</TableHead>
                        <TableHead className="text-right">Entry</TableHead>
                        <TableHead className="text-right">Exit</TableHead>
                        <TableHead className="text-right">P&amp;L</TableHead>
                        <TableHead className="text-right">Duration</TableHead>
                        <TableHead>Exit reason</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {result.trades.slice(0, shown).map((t) => (
                        <TableRow key={t.n}>
                          <TableCell className="num text-muted-foreground">{t.n}</TableCell>
                          <TableCell className="num">{dateShort(t.date)}</TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Badge variant={t.side === "SELL" ? "loss" : "profit"}>{t.side}</Badge>
                              <span className="font-medium">{t.instrument}</span>
                            </div>
                          </TableCell>
                          <TableCell className="num text-right">
                            {price(t.entry_price)} <span className="text-xs text-muted-foreground">{timeIST(t.entry_time)}</span>
                          </TableCell>
                          <TableCell className="num text-right">
                            {price(t.exit_price)} <span className="text-xs text-muted-foreground">{timeIST(t.exit_time)}</span>
                          </TableCell>
                          <TableCell className="text-right">
                            <Pnl value={t.pnl} className="justify-end" />
                          </TableCell>
                          <TableCell className="num text-right text-muted-foreground">{formatDuration(t.duration_min)}</TableCell>
                          <TableCell className="text-muted-foreground">{t.exit_reason}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {shown < result.trades.length && (
                    <div className="flex justify-center pt-3">
                      <Button variant="outline" size="sm" onClick={() => setShown((n) => n + 100)}>
                        Show more ({result.trades.length - shown} left)
                      </Button>
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
