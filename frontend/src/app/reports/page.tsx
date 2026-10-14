"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Download, FileText } from "lucide-react";
import { PnlBars } from "@/components/charts/pnl-bars";
import { PnlCalendar } from "@/components/reports/pnl-calendar";
import { Segmented, ToggleChip } from "@/components/segmented";
import { EmptyState, Pnl, Stat } from "@/components/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { logEvent } from "@/lib/api";
import { dateShort, daysAgo, dateTimeIST, int, isoDate, price, rupees, signedRupees, tone } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Trade, TradesResponse } from "@/lib/types";

type SortKey = "created_at" | "instrument" | "quantity" | "price" | "pnl";
const PAGE_SIZE = 50;
const RANGES = [
  { label: "7D", days: 6 },
  { label: "30D", days: 29 },
  { label: "90D", days: 89 },
  { label: "1Y", days: 364 },
];

function toCsv(rows: Trade[]): string {
  const head = ["date_time_ist", "instrument", "action", "quantity", "price", "order_id", "status", "strategy", "pnl", "mode", "reason"];
  const esc = (v: unknown) => {
    let s = v == null ? "" : String(v);
    // neutralise spreadsheet formula injection in free-text fields (numbers like -2665 must stay numeric)
    if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = rows.map((t) =>
    [dateTimeIST(t.created_at), t.instrument, t.action, t.quantity, t.price, t.order_id, t.status, t.strategy_tag, t.pnl, t.is_paper ? "paper" : "live", t.reason].map(esc).join(","),
  );
  return [head.join(","), ...lines].join("\n");
}

export default function ReportsPage() {
  const [from, setFrom] = useState(daysAgo(89));
  const [to, setTo] = useState(isoDate(new Date()));
  const [instrument, setInstrument] = useState("ALL");
  const [mode, setMode] = useState<"all" | "true" | "false">("all");
  const [query, setQuery] = useState("");
  const [closedOnly, setClosedOnly] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "created_at", dir: "desc" });
  const [page, setPage] = useState(0);

  const { data, error, isLoading } = useApi<TradesResponse>(`/trades?from=${from}&to=${to}&instrument=${instrument}&paper=${mode}`, { revalidateOnFocus: true });
  const trades = useMemo(() => data?.trades ?? [], [data]);

  const stats = useMemo(() => {
    const closed = trades.filter((t) => t.pnl != null);
    const daily: Record<string, number> = {};
    closed.forEach((t) => (daily[t.date] = (daily[t.date] ?? 0) + (t.pnl ?? 0)));
    const days = Object.entries(daily).sort(([a], [b]) => a.localeCompare(b));
    const total = closed.reduce((s, t) => s + (t.pnl ?? 0), 0);
    const wins = closed.filter((t) => (t.pnl ?? 0) > 0).length;
    const best = days.length ? days.reduce((a, b) => (b[1] > a[1] ? b : a)) : null;
    const worst = days.length ? days.reduce((a, b) => (b[1] < a[1] ? b : a)) : null;
    return { closed, daily, days, total, wins, best, worst };
  }, [trades]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    let r = trades.filter((t) => (!closedOnly || t.pnl != null) && (!q || `${t.instrument} ${t.strategy_tag ?? ""} ${t.reason ?? ""}`.toLowerCase().includes(q)));
    const dir = sort.dir === "asc" ? 1 : -1;
    r = [...r].sort((a, b) => {
      const av = a[sort.key] ?? (sort.key === "pnl" ? -Infinity : "");
      const bv = b[sort.key] ?? (sort.key === "pnl" ? -Infinity : "");
      return av < bv ? -dir : av > bv ? dir : 0;
    });
    return r;
  }, [trades, query, closedOnly, sort]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pageRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const setSortKey = (key: SortKey) => {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "instrument" ? "asc" : "desc" }));
    setPage(0);
  };

  const exportCsv = () => {
    const blob = new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `axiom-trades_${from}_to_${to}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    logEvent("reports", "export_trades", `Exported ${rows.length} trades to CSV (${from} → ${to})`, { rows: rows.length, from, to });
  };

  const SortHead = ({ k, children, right }: { k: SortKey; children: React.ReactNode; right?: boolean }) => {
    const active = sort.key === k;
    const Icon = !active ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
    return (
      <TableHead className={right ? "text-right" : ""} aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
        <button type="button" onClick={() => setSortKey(k)} className="inline-flex cursor-pointer items-center gap-1 uppercase tracking-wider hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {children}
          <Icon className={`size-3 ${active ? "text-foreground" : "opacity-50"}`} aria-hidden />
        </button>
      </TableHead>
    );
  };

  const winRate = stats.closed.length ? (stats.wins / stats.closed.length) * 100 : null;

  return (
    <div className="space-y-4 md:space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Reports</h1>
        <Button variant="outline" onClick={exportCsv} disabled={rows.length === 0}>
          <Download /> Export CSV
        </Button>
      </div>

      {data?.store === "sqlite" && (
        <Alert variant="info" title="Reading from the local database">
          Neon isn&apos;t configured, so trades are stored in a local SQLite file. Add DATABASE_URL to .env to use Neon.
        </Alert>
      )}

      <Card>
        <CardContent className="grid gap-4 p-4 md:p-5 lg:grid-cols-[auto_auto_1fr]">
          <div className="flex items-end gap-2">
            <div className="space-y-1.5">
              <Label htmlFor="rp-from">From</Label>
              <Input id="rp-from" type="date" value={from} max={to} onChange={(e) => { setFrom(e.target.value); setPage(0); }} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rp-to">To</Label>
              <Input id="rp-to" type="date" value={to} min={from} max={isoDate(new Date())} onChange={(e) => { setTo(e.target.value); setPage(0); }} />
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            {RANGES.map((r) => (
              <Button key={r.label} variant="outline" size="sm" onClick={() => { setFrom(daysAgo(r.days)); setTo(isoDate(new Date())); setPage(0); }}>
                {r.label}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-3 lg:justify-end">
            <Segmented
              label="Instrument filter"
              value={instrument}
              onChange={(v) => { setInstrument(v); setPage(0); }}
              options={[
                { value: "ALL", label: "All" },
                { value: "NIFTY", label: "Nifty" },
                { value: "BANKNIFTY", label: "Bank Nifty" },
                { value: "SENSEX", label: "Sensex" },
                { value: "FINNIFTY", label: "Fin Nifty" },
              ]}
            />
            <Segmented
              label="Trading mode filter"
              value={mode}
              onChange={(v) => { setMode(v); setPage(0); }}
              options={[
                { value: "all", label: "All modes" },
                { value: "true", label: "Paper" },
                { value: "false", label: "Live" },
              ]}
            />
          </div>
        </CardContent>
      </Card>

      {error && <Alert variant="error" title="Couldn't load trades">{error.message}</Alert>}

      <section aria-label="Summary" className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {isLoading && !data ? (
          // the real tile markup, so every block below stays put when the numbers arrive
          Array.from({ length: 5 }).map((_, i) => <Stat key={i} loading label="Loading" value="0" sub="Loading" className={i === 0 ? "col-span-2 md:col-span-1" : undefined} />)
        ) : (
          <>
            <Stat className="col-span-2 md:col-span-1" label="Total P&L" value={<Pnl value={stats.total} icon={false} />} tone={tone(stats.total)} sub={`${stats.days.length} trading day${stats.days.length === 1 ? "" : "s"}`} />
            <Stat label="Total trades" value={stats.closed.length} sub={`${trades.length} orders`} />
            <Stat label="Win rate" value={winRate != null ? `${winRate.toFixed(1)}%` : "—"} sub={`${stats.wins} W · ${stats.closed.length - stats.wins} L`} />
            <Stat label="Best day" value={stats.best ? signedRupees(stats.best[1]) : "—"} tone={stats.best ? tone(stats.best[1]) : undefined} sub={stats.best ? dateShort(stats.best[0]) : "No closed trades"} />
            <Stat label="Worst day" value={stats.worst ? signedRupees(stats.worst[1]) : "—"} tone={stats.worst ? tone(stats.worst[1]) : undefined} sub={stats.worst ? dateShort(stats.worst[0]) : "No closed trades"} />
          </>
        )}
      </section>

      {data && trades.length === 0 ? (
        <Card>
          <EmptyState icon={<FileText />} title="No trades in this range">
            Trades appear here once the bot has fired orders (paper or live). Try widening the date range or clearing filters.
          </EmptyState>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 md:gap-5 xl:grid-cols-5">
            <Card className="xl:col-span-3">
              <CardHeader>
                <CardTitle>P&amp;L calendar</CardTitle>
                <CardDescription>Realised P&amp;L per day. Darker = bigger move.</CardDescription>
              </CardHeader>
              <CardContent>
                {data ? (
                  <PnlCalendar daily={stats.daily} from={from} to={to} />
                ) : (
                  // the calendar's layout depends only on the date range, so an empty dimmed one has exactly the real height
                  <div className="animate-pulse opacity-40" aria-hidden>
                    <PnlCalendar daily={{}} from={from} to={to} />
                  </div>
                )}
              </CardContent>
            </Card>
            <Card className="xl:col-span-2">
              <CardHeader>
                <CardTitle>Daily P&amp;L</CardTitle>
                <CardDescription>Gross of brokerage and taxes.</CardDescription>
              </CardHeader>
              <CardContent>
                {!data ? (
                  <Skeleton className="h-[260px]" aria-hidden />
                ) : stats.days.length ? (
                  <PnlBars
                    data={stats.days.map(([date, pnl]) => ({ date, pnl }))}
                    ariaLabel={`Daily P&L bar chart across ${stats.days.length} days, total ${rupees(stats.total)}.`}
                  />
                ) : (
                  <p className="py-10 text-center text-[13px] text-muted-foreground">No closed trades to chart.</p>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="gap-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <CardTitle>Trade history ({rows.length})</CardTitle>
                <div className="flex flex-wrap items-center gap-2">
                  <ToggleChip pressed={closedOnly} onToggle={() => { setClosedOnly((v) => !v); setPage(0); }}>
                    Closed trades only
                  </ToggleChip>
                  <div className="w-full sm:w-56">
                    <Input type="search" placeholder="Filter instrument / strategy…" aria-label="Filter trades" value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} />
                  </div>
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-0 md:px-0">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <SortHead k="created_at">Date / time</SortHead>
                    <SortHead k="instrument">Instrument</SortHead>
                    <TableHead>Action</TableHead>
                    <SortHead k="quantity" right>Qty</SortHead>
                    <SortHead k="price" right>Price</SortHead>
                    <SortHead k="pnl" right>P&amp;L</SortHead>
                    <TableHead>Strategy</TableHead>
                    <TableHead>Mode</TableHead>
                    <TableHead>Note</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pageRows.map((t) => (
                    <TableRow key={t.id}>
                      <TableCell className="num text-muted-foreground">{dateTimeIST(t.created_at)}</TableCell>
                      <TableCell className="font-medium">{t.instrument}</TableCell>
                      <TableCell>
                        <Badge variant={t.action === "BUY" ? "profit" : "loss"}>{t.action}</Badge>
                      </TableCell>
                      <TableCell className="num text-right">{int(t.quantity)}</TableCell>
                      <TableCell className="num text-right">{price(t.price)}</TableCell>
                      <TableCell className="text-right">{t.pnl == null ? <span className="text-muted-foreground">—</span> : <Pnl value={t.pnl} className="justify-end" />}</TableCell>
                      <TableCell className="text-muted-foreground">{t.strategy_tag ?? "—"}</TableCell>
                      <TableCell>
                        <Badge variant={t.is_paper ? "warn" : "live"}>{t.is_paper ? "PAPER" : "LIVE"}</Badge>
                      </TableCell>
                      <TableCell className="max-w-[14rem] truncate text-muted-foreground" title={t.reason ?? ""}>
                        {t.reason ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {rows.length === 0 && <p className="py-8 text-center text-[13px] text-muted-foreground">No trades match these filters.</p>}
              {pages > 1 && (
                <div className="flex items-center justify-between gap-3 px-4 pt-4 md:px-5">
                  <span className="text-xs text-muted-foreground">
                    Page {page + 1} of {pages}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                      Previous
                    </Button>
                    <Button variant="outline" size="sm" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
