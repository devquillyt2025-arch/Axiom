"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type UTCTimestamp,
} from "lightweight-charts";
import { baseChartOptions, C } from "@/lib/chart-theme";
import { bollinger, ema, macd, rsi, type Series } from "@/lib/indicators";
import { price } from "@/lib/format";
import type { Candle } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface Indicators {
  ema9: boolean;
  ema21: boolean;
  ema50: boolean;
  bb: boolean;
  rsi: boolean;
  macd: boolean;
}

type Refs = Partial<Record<"ema9" | "ema21" | "ema50" | "bbU" | "bbM" | "bbL" | "rsi" | "macdL" | "macdS" | "macdH", ISeriesApi<SeriesType>>>;

const toLine = (candles: Candle[], values: Series) => {
  const out: { time: UTCTimestamp; value: number }[] = [];
  candles.forEach((c, i) => {
    const v = values[i];
    if (v != null && Number.isFinite(v)) out.push({ time: c.time as UTCTimestamp, value: v });
  });
  return out;
};

export function CandleChart({
  candles,
  show,
  resetKey,
  className,
  ariaLabel,
}: {
  candles: Candle[];
  show: Indicators;
  /** Changes when a different symbol/timeframe has loaded — re-frames the view. */
  resetKey: string;
  className?: string;
  ariaLabel: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const indRef = useRef<Refs>({});
  // The chart library throws (and would blank the page) on unsorted / duplicate timestamps, so
  // normalise defensively even though the API already guarantees ascending unique bars.
  const clean = useMemo(() => {
    const byTime = new Map<number, Candle>();
    for (const c of candles) if (Number.isFinite(c.time) && Number.isFinite(c.close)) byTime.set(c.time, c);
    return Array.from(byTime.values()).sort((a, b) => a.time - b.time);
  }, [candles]);
  const candlesRef = useRef(clean);
  candlesRef.current = clean;
  const [hover, setHover] = useState<Candle | null>(null);

  const applyData = () => {
    try {
      applyDataUnsafe();
    } catch (e) {
      console.error("Axiom chart: could not draw data", e);
    }
  };

  const applyDataUnsafe = () => {
    const data = candlesRef.current;
    if (!candleRef.current || !volRef.current) return;
    candleRef.current.setData(data.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })));
    volRef.current.setData(
      data.map((c) => ({ time: c.time as UTCTimestamp, value: c.volume, color: c.close >= c.open ? `${C.up}55` : `${C.down}55` })),
    );
    const closes = data.map((c) => c.close);
    const r = indRef.current;
    if (r.ema9) r.ema9.setData(toLine(data, ema(closes, 9)));
    if (r.ema21) r.ema21.setData(toLine(data, ema(closes, 21)));
    if (r.ema50) r.ema50.setData(toLine(data, ema(closes, 50)));
    if (r.bbU) {
      const b = bollinger(closes);
      r.bbU.setData(toLine(data, b.upper));
      r.bbM?.setData(toLine(data, b.mid));
      r.bbL?.setData(toLine(data, b.lower));
    }
    if (r.rsi) r.rsi.setData(toLine(data, rsi(closes)));
    if (r.macdL) {
      const m = macd(closes);
      r.macdL.setData(toLine(data, m.macd));
      r.macdS?.setData(toLine(data, m.signal));
      r.macdH?.setData(
        data.flatMap((c, i) => {
          const v = m.hist[i];
          return v == null ? [] : [{ time: c.time as UTCTimestamp, value: v, color: v >= 0 ? `${C.up}aa` : `${C.down}aa` }];
        }),
      );
    }
  };

  // 1) create the chart once
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const chart = createChart(host, baseChartOptions(400));
    chartRef.current = chart;
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: C.up,
      downColor: C.down,
      borderVisible: false,
      wickUpColor: C.up,
      wickDownColor: C.down,
      priceLineColor: C.text,
    });
    volRef.current = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    chart.subscribeCrosshairMove((p) => {
      const d = p.seriesData.get(candleRef.current as ISeriesApi<SeriesType>) as { open: number; high: number; low: number; close: number } | undefined;
      if (!p.time || !d) return setHover(null);
      setHover({ time: p.time as number, open: d.open, high: d.high, low: d.low, close: d.close, volume: 0 });
    });
    return () => {
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volRef.current = null;
      indRef.current = {};
    };
  }, []);

  // 2) rebuild indicator series/panes whenever the set of enabled overlays changes
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    Object.values(indRef.current).forEach((s) => s && chart.removeSeries(s));
    indRef.current = {};
    while (chart.panes().length > 1) chart.removePane(chart.panes().length - 1);

    const line = (color: string, pane = 0, extra: object = {}) =>
      chart.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...extra }, pane);
    const r: Refs = {};
    if (show.ema9) r.ema9 = line(C.ema9);
    if (show.ema21) r.ema21 = line(C.ema21);
    if (show.ema50) r.ema50 = line(C.ema50);
    if (show.bb) {
      r.bbU = line(C.bb, 0, { lineStyle: LineStyle.Dashed });
      r.bbM = line(C.bb, 0, { lineStyle: LineStyle.Dotted });
      r.bbL = line(C.bb, 0, { lineStyle: LineStyle.Dashed });
    }
    let pane = 1;
    if (show.rsi) {
      r.rsi = line(C.rsi, pane, { lineWidth: 2, lastValueVisible: true, priceFormat: { type: "price", precision: 1, minMove: 0.1 } });
      for (const lvl of [30, 70]) r.rsi.createPriceLine({ price: lvl, color: C.border, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: "" });
      pane += 1;
    }
    if (show.macd) {
      r.macdH = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
      r.macdL = line(C.macd, pane, { lineWidth: 2 });
      r.macdS = line(C.signal, pane);
      pane += 1;
    }
    indRef.current = r;
    const panes = chart.panes();
    panes.forEach((p, i) => p.setStretchFactor(i === 0 ? 3 : 1));
    applyData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show.ema9, show.ema21, show.ema50, show.bb, show.rsi, show.macd]);

  // 3) data
  useEffect(() => {
    applyData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clean]);

  // 4) re-frame on symbol/timeframe change: last ~110 bars, not the whole history
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || candlesRef.current.length === 0) return;
    const n = candlesRef.current.length;
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 110), to: n + 6 });
  }, [resetKey]);

  const shown = hover ?? clean[clean.length - 1];
  const chg = shown ? shown.close - shown.open : 0;
  const extra = (show.rsi ? 1 : 0) + (show.macd ? 1 : 0);

  return (
    <div className={cn("min-w-0", className)}>
      <div className="num mb-2 flex min-h-5 flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-hidden>
        {shown && (
          <>
            <span>O <b className="font-medium text-foreground">{price(shown.open)}</b></span>
            <span>H <b className="font-medium text-foreground">{price(shown.high)}</b></span>
            <span>L <b className="font-medium text-foreground">{price(shown.low)}</b></span>
            <span>C <b className={cn("font-medium", chg >= 0 ? "text-profit" : "text-loss")}>{price(shown.close)}</b></span>
          </>
        )}
      </div>
      <div
        ref={hostRef}
        role="img"
        aria-label={ariaLabel}
        className="chart-host [--h:340px] md:[--h:440px]"
        style={{ height: `calc(var(--h) + ${extra * 150}px)` }}
      />
    </div>
  );
}
