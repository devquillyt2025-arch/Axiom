"use client";

import { Layers } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, Pnl } from "@/components/stat";
import { int, price } from "@/lib/format";
import type { Position } from "@/lib/types";

export function PositionsTable({ positions, unmanaged }: { positions: Position[]; unmanaged?: boolean }) {
  const total = positions.reduce((s, p) => s + p.pnl, 0);
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Live positions</CardTitle>
        {positions.length > 0 && (
          <span className="text-xs text-muted-foreground">
            Unrealised <Pnl value={total} className="ml-1 text-[13px] font-medium" />
          </span>
        )}
      </CardHeader>
      <CardContent className="px-0 md:px-0">
        {positions.length === 0 ? (
          <EmptyState icon={<Layers />} title="No open positions">
            Positions opened by the bot appear here with live P&L.
          </EmptyState>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Instrument</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Avg price</TableHead>
                <TableHead className="text-right">LTP</TableHead>
                <TableHead className="text-right">Unrealised P&amp;L</TableHead>
                <TableHead className="text-right">SL</TableHead>
                <TableHead className="text-right">Target</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Badge variant={p.side === "SELL" ? "loss" : "profit"}>{p.side}</Badge>
                      <span className="font-medium">{p.instrument}</span>
                      {unmanaged && <Badge variant="warn">UNMANAGED</Badge>}
                    </div>
                  </TableCell>
                  <TableCell className="num text-right">{int(p.qty)}</TableCell>
                  <TableCell className="num text-right">{price(p.avg_price)}</TableCell>
                  <TableCell className="num text-right">{price(p.ltp)}</TableCell>
                  <TableCell className="text-right">
                    <Pnl value={p.pnl} className="justify-end" />
                  </TableCell>
                  <TableCell className="num text-right text-muted-foreground">{p.sl != null ? price(p.sl) : "—"}</TableCell>
                  <TableCell className="num text-right text-muted-foreground">{p.target != null ? price(p.target) : "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
