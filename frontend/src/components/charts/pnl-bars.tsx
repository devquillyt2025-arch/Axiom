"use client";

import { useEffect, useRef } from "react";
import { HistogramSeries, createChart, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { baseChartOptions, C } from "@/lib/chart-theme";

/** Daily P&L histogram — profit bars up in green, loss bars down in red. `date` is YYYY-MM-DD. */
export function PnlBars({ data, ariaLabel, height = 260 }: { data: { date: string; pnl: number }[]; ariaLabel: string; height?: number }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const chart = createChart(host, {
      ...baseChartOptions(height),
      timeScale: { borderColor: C.border, timeVisible: false, rightOffset: 2, barSpacing: 14, minBarSpacing: 3 },
    });
    chartRef.current = chart;
    seriesRef.current = chart.addSeries(HistogramSeries, {
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat: { type: "custom", formatter: (v: number) => `${v < 0 ? "-" : ""}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`, minMove: 1 },
    });
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const s = seriesRef.current;
    if (!s) return;
    s.setData(data.map((d) => ({ time: d.date, value: d.pnl, color: d.pnl >= 0 ? C.profit : C.loss })));
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  return <div ref={hostRef} role="img" aria-label={ariaLabel} className="chart-host" style={{ height }} />;
}
