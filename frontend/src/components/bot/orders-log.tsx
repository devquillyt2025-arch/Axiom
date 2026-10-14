"use client";

import { Inbox } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, Pnl } from "@/components/stat";
import { int, price, timeIST } from "@/lib/format";
import type { LogLine, OrdersToday } from "@/lib/types";
import { cn } from "@/lib/utils";

export function OrdersLog({ data, loading }: { data: OrdersToday | undefined; loading: boolean }) {
  const rows = [...(data?.orders ?? [])].reverse(); // newest first
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Today&apos;s orders</CardTitle>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="size-1.5 animate-pulse-dot rounded-full bg-profit" aria-hidden /> refreshes every 3s
        </span>
      </CardHeader>
      <CardContent className="px-0 md:px-0">
        {loading && !data ? (
          <div className="space-y-2 px-4">
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState icon={<Inbox />} title="No orders yet today">
            Entries and exits fired by the bot are listed here, paper and live.
          </EmptyState>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Time</TableHead>
                <TableHead>Mode</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Instrument</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead className="text-right">P&amp;L</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Note</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((o) => (
                <TableRow key={o.id}>
                  <TableCell className="num text-muted-foreground">{timeIST(o.created_at)}</TableCell>
                  <TableCell>
                    <Badge variant={o.is_paper ? "warn" : "live"}>{o.is_paper ? "PAPER" : "LIVE"}</Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={o.action === "BUY" ? "profit" : "loss"}>{o.action}</Badge>
                  </TableCell>
                  <TableCell className="font-medium">{o.instrument}</TableCell>
                  <TableCell className="num text-right">{int(o.quantity)}</TableCell>
                  <TableCell className="num text-right">{price(o.price)}</TableCell>
                  <TableCell className="text-right">{o.pnl == null ? <span className="text-muted-foreground">—</span> : <Pnl value={o.pnl} className="justify-end" />}</TableCell>
                  <TableCell className="capitalize text-muted-foreground">{o.status}</TableCell>
                  <TableCell className="max-w-[16rem] truncate text-muted-foreground" title={o.reason ?? ""}>
                    {o.reason ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

const levelClass: Record<string, string> = { INFO: "text-muted-foreground", WARN: "text-warn", ERROR: "text-loss" };

export function BotLogs({ logs }: { logs: LogLine[] }) {
  const rows = [...logs].reverse();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Bot activity</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="py-4 text-center text-[13px] text-muted-foreground">Nothing logged yet. Start the bot to see its decisions here.</p>
        ) : (
          <ul className="max-h-72 space-y-1 overflow-y-auto pr-1 font-mono text-xs leading-5">
            {rows.map((l, i) => (
              <li key={`${l.created_at}-${i}`} className="flex gap-2">
                <span className="shrink-0 text-muted-foreground/70">{timeIST(l.created_at)}</span>
                <span className={cn("w-10 shrink-0 font-medium", levelClass[l.level] ?? "text-muted-foreground")}>{l.level}</span>
                <span className="min-w-0 break-words">{l.message}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
