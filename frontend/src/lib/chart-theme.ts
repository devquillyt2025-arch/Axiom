import { ColorType, CrosshairMode, type DeepPartial, type ChartOptions } from "lightweight-charts";

// Hex mirrors of the CSS tokens in globals.css (the canvas can't read CSS variables).
export const C = {
  bg: "#0A0A0A",
  text: "#A1A1AA",
  grid: "#17171A",
  border: "#2A2A2E",
  up: "#26A69A", // TradingView-style candle colours
  down: "#EF5350",
  profit: "#34D399",
  loss: "#F87171",
  ema9: "#FBBF24",
  ema21: "#60A5FA",
  ema50: "#C084FC",
  bb: "#94A3B8",
  rsi: "#F472B6",
  macd: "#60A5FA",
  signal: "#FBBF24",
  equity: "#60A5FA",
} as const;

export function baseChartOptions(height: number): DeepPartial<ChartOptions> {
  return {
    height,
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: C.bg },
      textColor: C.text,
      fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
      fontSize: 11,
      panes: { separatorColor: C.border, enableResize: true },
    },
    grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
    rightPriceScale: { borderColor: C.border },
    timeScale: { borderColor: C.border, timeVisible: true, secondsVisible: false, rightOffset: 6 },
    crosshair: { mode: CrosshairMode.Normal },
    localization: { locale: "en-IN" },
  };
}
