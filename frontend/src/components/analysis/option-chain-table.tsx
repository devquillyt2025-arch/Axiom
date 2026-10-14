"use client";

import { Fragment } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { compactIN, price } from "@/lib/format";
import type { ChainRow, OptionChain } from "@/lib/types";
import { cn } from "@/lib/utils";

/** OI cell with a proportional background bar so open-interest "walls" are visible at a glance. */
function OiCell({ value, max, side, wall }: { value: number; max: number; side: "ce" | "pe"; wall: boolean }) {
  const w = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <TableCell className="relative text-right">
      <span
        aria-hidden
        className={cn("absolute inset-y-1 rounded-sm", side === "ce" ? "right-0 bg-loss/15" : "left-0 bg-profit/15", wall && (side === "ce" ? "bg-loss/30" : "bg-profit/30"))}
        style={{ width: `${w}%` }}
      />
      <span className={cn("num relative", wall && "font-semibold")}>{compactIN(value)}</span>
    </TableCell>
  );
}

function pcrTone(p: number | null) {
  if (p == null) return "text-muted-foreground";
  if (p >= 1.2) return "text-profit";
  if (p <= 0.7) return "text-loss";
  return "text-foreground";
}

export function OptionChainTable({ chain }: { chain: OptionChain }) {
  const rows: ChainRow[] = chain.rows;
  const maxCe = Math.max(0, ...rows.map((r) => r.ce.oi));
  const maxPe = Math.max(0, ...rows.map((r) => r.pe.oi));
  return (
    <Table className="min-w-[760px]">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead colSpan={3} className="border-r text-center text-loss/90">
            Calls (CE)
          </TableHead>
          <TableHead className="text-center" />
          <TableHead colSpan={3} className="border-l text-center text-profit/90">
            Puts (PE)
          </TableHead>
          <TableHead className="text-right" />
        </TableRow>
        <TableRow className="hover:bg-transparent">
          <TableHead className="text-right">OI</TableHead>
          <TableHead className="text-right">IV</TableHead>
          <TableHead className="border-r text-right">LTP</TableHead>
          <TableHead className="text-center">Strike</TableHead>
          <TableHead className="border-l text-right">LTP</TableHead>
          <TableHead className="text-right">IV</TableHead>
          <TableHead className="text-right">OI</TableHead>
          <TableHead className="text-right">PCR</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => {
          const atm = r.strike === chain.atm;
          const ceItm = r.strike < chain.spot;
          const peItm = r.strike > chain.spot;
          return (
            <Fragment key={r.strike}>
              <TableRow className={cn(atm && "bg-primary/10 hover:bg-primary/15")}>
                <OiCell value={r.ce.oi} max={maxCe} side="ce" wall={r.strike === chain.resistance} />
                <TableCell className={cn("num text-right text-muted-foreground", ceItm && "bg-muted/30")}>{r.ce.iv ? r.ce.iv.toFixed(1) : "—"}</TableCell>
                <TableCell className={cn("num border-r text-right font-medium", ceItm && "bg-muted/30")}>{price(r.ce.ltp)}</TableCell>
                <TableCell className="num text-center font-semibold">
                  {r.strike.toLocaleString("en-IN")}
                  {atm && <span className="ml-1.5 rounded bg-primary/25 px-1 py-px align-middle text-[10px] font-medium text-info">ATM</span>}
                </TableCell>
                <TableCell className={cn("num border-l text-right font-medium", peItm && "bg-muted/30")}>{price(r.pe.ltp)}</TableCell>
                <TableCell className={cn("num text-right text-muted-foreground", peItm && "bg-muted/30")}>{r.pe.iv ? r.pe.iv.toFixed(1) : "—"}</TableCell>
                <OiCell value={r.pe.oi} max={maxPe} side="pe" wall={r.strike === chain.support} />
                <TableCell className={cn("num text-right", pcrTone(r.pcr))}>{r.pcr != null ? r.pcr.toFixed(2) : "—"}</TableCell>
              </TableRow>
            </Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}
