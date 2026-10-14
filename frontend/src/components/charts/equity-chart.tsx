"use client";

import { useEffect, useRef } from "react";
import { BaselineSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { baseChartOptions, C } from "@/lib/chart-theme";

/** Equity curve: green above starting capital, red below it. */
export function EquityChart({
  data,
  baseValue,
  ariaLabel,
  height = 300,
}: {
  data: { time: number; value: number }[];
  baseValue: number;
  ariaLabel: string;
  height?: number;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Baseline"> | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const chart = createChart(host, baseChartOptions(height));
    chartRef.current = chart;
    seriesRef.current = chart.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: baseValue },
      topLineColor: C.profit,
      topFillColor1: "rgba(52,211,153,0.28)",
      topFillColor2: "rgba(52,211,153,0.02)",
      bottomLineColor: C.loss,
      bottomFillColor1: "rgba(248,113,113,0.02)",
      bottomFillColor2: "rgba(248,113,113,0.28)",
      lineWidth: 2,
      priceLineVisible: false,
      priceFormat: { type: "custom", formatter: (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`, minMove: 1 },
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
    s.applyOptions({ baseValue: { type: "price", price: baseValue } });
    s.setData(data.map((d) => ({ time: d.time as UTCTimestamp, value: d.value })));
    chartRef.current?.timeScale().fitContent();
  }, [data, baseValue]);

  return <div ref={hostRef} role="img" aria-label={ariaLabel} className="chart-host" style={{ height }} />;
}
