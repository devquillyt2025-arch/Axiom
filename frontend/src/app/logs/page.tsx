"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronRight, Download, Inbox, Pause, Play, Search } from "lucide-react";
import { Segmented } from "@/components/segmented";
import { EmptyState } from "@/components/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, errorMessage, logEvent } from "@/lib/api";
import { dateTimeSecIST, isoDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { LogCategory, LogEntry, LogLevel, LogRange, LogsResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const RANGES: { value: LogRange; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "all", label: "All" },
];

type BadgeVariant = "default" | "muted" | "outline" | "profit" | "loss" | "warn" | "live";
const TYPES: { value: LogCategory; label: string; variant: BadgeVariant }[] = [
  { value: "all", label: "Everything", variant: "muted" },
  { value: "navigation", label: "Navigation", variant: "muted" },
  { value: "bot", label: "Bot actions", variant: "default" },
  { value: "engine", label: "Bot engine", variant: "muted" },
  { value: "trade", label: "Trades", variant: "outline" },
  { value: "backtest", label: "Backtests", variant: "default" },
  { value: "reports", label: "Reports", variant: "outline" },
  { value: "suggestions", label: "Suggestions", variant: "default" },
  { value: "auth", label: "Login", variant: "warn" },
  { value: "system", label: "System & errors", variant: "muted" },
];
const TYPE_BY_VALUE = Object.fromEntries(TYPES.map((t) => [t.value, t]));
const LEVELS: { value: LogLevel; label: string }[] = [
  { value: "all", label: "All levels" },
  { value: "INFO", label: "Info" },
  { value: "WARN", label: "Warnings" },
  { value: "ERROR", label: "Errors" },
];

const keyOf = (e: LogEntry) => `${e.source}:${e.id}`;
const MAX_ROWS = 1000;

/** Everything fetched for one set of filters. It only grows, so live refreshes and "load older" never lose rows. */
interface Loaded {
  sig: string;
  map: Map<string, LogEntry>;
  cursor: string | null | undefined; // where "load older" continues from; null = start of the range reached
  olderLoaded: boolean;
}

function LevelCell({ level }: { level: string }) {
  if (level === "ERROR") return <Badge variant="loss">ERROR</Badge>;
  if (level === "WARN") return <Badge variant="warn">WARN</Badge>;
  return <span className="text-xs text-muted-foreground">INFO</span>;
}

function csvCell(v: unknown): string {
  let s = v == null ? "" : String(v);
  // neutralise spreadsheet formula injection in free-text fields
  if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export default function LogsPage() {
  const [range, setRange] = useState<LogRange>("today");
  const [category, setCategory] = useState<LogCategory>("all");
  const [level, setLevel] = useState<LogLevel>("all");
  const [query, setQuery] = useState("");
  const [live, setLive] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);

  const sig = `${range}|${category}|${level}`;
  const qs = `range=${range}&category=${category}&level=${level}&limit=200`;
  const { data, error } = useApi<LogsResponse>(`/logs?${qs}`, { refreshInterval: live ? 5000 : 0 });
  const [loaded, setLoaded] = useState<Loaded>({ sig, map: new Map(), cursor: undefined, olderLoaded: false });

  // `data` can still be the previous filters' response while the new one loads; only merge a matching one.
  const fresh = !!data && data.range === range && data.category === category && data.level === level;
  useEffect(() => {
    if (!data || data.range !== range || data.category !== category || data.level !== level) return;
    setLoaded((prev) => {
      const base: Loaded = prev.sig === sig ? prev : { sig, map: new Map(), cursor: undefined, olderLoaded: false };
      const map = new Map(base.map);
      for (const e of data.entries) map.set(keyOf(e), e);
      // until "load older" is used the cursor follows the newest page; after that it belongs to the oldest page loaded
      return { sig, map, olderLoaded: base.olderLoaded, cursor: base.olderLoaded ? base.cursor : data.next_before };
    });
  }, [data, range, category, level, sig]);

  const current = loaded.sig === sig ? loaded : null;
  const rows = useMemo(
    () => (current ? Array.from(current.map.values()).sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)) : []),
    [current],
  );
  const haystack = useMemo(
    () => rows.map((e) => `${e.summary} ${e.category} ${e.action} ${e.level} ${e.details ? JSON.stringify(e.details) : ""}`.toLowerCase()),
    [rows],
  );
  const q = query.trim().toLowerCase();
  const filtered = useMemo(() => (q ? rows.filter((_, i) => haystack[i].includes(q)) : rows), [rows, haystack, q]);
  const shown = filtered.slice(0, MAX_ROWS);
  const errors = rows.filter((e) => e.level === "ERROR").length;
  const warnings = rows.filter((e) => e.level === "WARN").length;
  const waiting = !fresh && !error;

  const loadOlder = async () => {
    if (!current?.cursor || busy) return;
    setBusy(true);
    setMoreError(null);
    try {
      const page = await api.get<LogsResponse>(`/logs?${qs}&before=${encodeURIComponent(current.cursor)}`);
      setLoaded((prev) => {
        if (prev.sig !== sig) return prev;
        const map = new Map(prev.map);
        for (const e of page.entries) map.set(keyOf(e), e);
        return { ...prev, map, cursor: page.next_before, olderLoaded: true };
      });
    } catch (e) {
      setMoreError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (k: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(k)) next.add(k);
      return next;
    });

  const exportCsv = () => {
    const head = ["created_at_utc", "time_ist", "source", "category", "action", "level", "summary", "details"];
    const lines = filtered.map((e) =>
      [e.created_at, dateTimeSecIST(e.created_at), e.source, e.category, e.action, e.level, e.summary, e.details ? JSON.stringify(e.details) : ""].map(csvCell).join(","),
    );
    const blob = new Blob([[head.join(","), ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `axiom-logs_${isoDate(new Date())}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    logEvent("reports", "export_logs", `Exported ${filtered.length} log rows to CSV`, { rows: filtered.length, range, category, level });
  };

  return (
    <div className="space-y-4 md:space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="page-title">Logs</h1>
          <p className="mt-1 max-w-2xl text-[13px] text-muted-foreground">
            Everything you do in Axiom, what the bot engine says and every order it places — newest first, times in IST. Passwords, tokens and keys are never stored here.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" className="min-w-[12.5rem]" onClick={() => setLive((v) => !v)} aria-pressed={live}>
            {live ? <Pause /> : <Play />} {live ? "Pause live updates" : "Resume live updates"}
          </Button>
          <Button variant="outline" size="sm" onClick={exportCsv} disabled={filtered.length === 0}>
            <Download /> Export CSV
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Segmented label="Time range" value={range} onChange={setRange} options={RANGES} />
        <div className="w-44">
          <Select value={category} onValueChange={(v) => setCategory(v as LogCategory)}>
            <SelectTrigger aria-label="Type of event">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="w-36">
          <Select value={level} onValueChange={(v) => setLevel(v as LogLevel)}>
            <SelectTrigger aria-label="Level">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LEVELS.map((l) => (
                <SelectItem key={l.value} value={l.value}>
                  {l.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="relative min-w-[12rem] flex-1 md:max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input className="pl-9" type="search" placeholder="Search the loaded entries…" aria-label="Search logs" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>

      {error && !current?.map.size && (
        <Alert variant="error" title="Couldn't load the logs">
          {errorMessage(error)}
        </Alert>
      )}

      <Card className="min-h-[30rem]">
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle>Timeline</CardTitle>
          <span className="flex items-center gap-2 text-xs text-muted-foreground">
            {live && <span className="size-1.5 animate-pulse-dot rounded-full bg-profit" aria-hidden />}
            {filtered.length.toLocaleString("en-IN")} shown
            {filtered.length !== rows.length && ` of ${rows.length.toLocaleString("en-IN")} loaded`}
            {errors > 0 && <span className="text-loss">· {errors} error{errors > 1 ? "s" : ""}</span>}
            {warnings > 0 && <span className="text-warn">· {warnings} warning{warnings > 1 ? "s" : ""}</span>}
          </span>
        </CardHeader>
        <CardContent className="px-0 md:px-0">
          {waiting ? (
            <div className="space-y-2 px-4" aria-busy="true" aria-label="Loading logs">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : shown.length === 0 ? (
            <EmptyState icon={<Inbox />} title={rows.length ? "No entries match your search" : "Nothing logged for these filters"}>
              {rows.length ? "Clear the search box to see everything that was loaded." : "Actions you take in Axiom appear here as you make them. Try a wider time range."}
            </EmptyState>
          ) : (
            <Table className="min-w-[44rem]">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-44">Time (IST)</TableHead>
                  <TableHead className="w-36">Type</TableHead>
                  <TableHead className="w-24">Level</TableHead>
                  <TableHead>What happened</TableHead>
                  <TableHead className="w-12">
                    <span className="sr-only">Details</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((e) => {
                  const k = keyOf(e);
                  const type = TYPE_BY_VALUE[e.category];
                  const hasDetails = !!e.details && Object.keys(e.details).length > 0;
                  const open = expanded.has(k);
                  return (
                    <LogRow key={k} entry={e} label={type?.label ?? e.category} variant={type?.variant ?? "muted"} hasDetails={hasDetails} open={open} onToggle={() => toggle(k)} />
                  );
                })}
              </TableBody>
            </Table>
          )}

          {!waiting && rows.length > 0 && (
            <div className="flex flex-col items-center gap-2 px-4 pb-1 pt-4 text-xs text-muted-foreground">
              {filtered.length > MAX_ROWS && <p>Showing the newest {MAX_ROWS.toLocaleString("en-IN")} — narrow the filters or search to see the rest.</p>}
              {moreError && <p className="text-loss">Couldn&apos;t load older entries: {moreError}</p>}
              {current?.cursor ? (
                <Button variant="outline" size="sm" onClick={loadOlder} loading={busy}>
                  Load older entries
                </Button>
              ) : (
                <p>That&apos;s everything in this range.</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function LogRow({
  entry: e, label, variant, hasDetails, open, onToggle,
}: {
  entry: LogEntry;
  label: string;
  variant: BadgeVariant;
  hasDetails: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <TableRow className={cn(hasDetails && "cursor-pointer")} onClick={hasDetails ? onToggle : undefined}>
        <TableCell className="num text-muted-foreground">{dateTimeSecIST(e.created_at)}</TableCell>
        <TableCell>
          <Badge variant={variant}>{label}</Badge>
        </TableCell>
        <TableCell>
          <LevelCell level={e.level} />
        </TableCell>
        <TableCell className="whitespace-normal break-words">{e.summary}</TableCell>
        <TableCell className="text-right">
          {hasDetails && (
            <button
              type="button"
              aria-expanded={open}
              aria-label={open ? "Hide details" : "Show details"}
              onClick={(ev) => {
                ev.stopPropagation();
                onToggle();
              }}
              className="inline-flex size-8 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ChevronRight className={cn("size-4 transition-transform duration-150", open && "rotate-90")} aria-hidden />
            </button>
          )}
        </TableCell>
      </TableRow>
      {open && hasDetails && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={5} className="whitespace-normal bg-muted/20 py-3">
            <pre className="max-h-64 overflow-auto rounded-md bg-background/60 p-3 font-mono text-xs leading-5">{JSON.stringify(e.details, null, 2)}</pre>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}
