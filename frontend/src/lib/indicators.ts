/**
 * Chart-overlay indicators. Same definitions as backend/core/indicators.py (pandas):
 *   EMA  = ewm(span=n, adjust=False)      RSI = Wilder RMA (alpha = 1/n)
 *   MACD = EMA12 - EMA26, signal EMA9      BB  = SMA(n) ± k·σ  (population σ)
 * Values before the indicator has enough history are `null` so the chart doesn't draw them.
 */
export type Series = (number | null)[];

export function ema(values: number[], n: number): Series {
  const a = 2 / (n + 1);
  const out: Series = [];
  let prev = 0;
  values.forEach((v, i) => {
    prev = i === 0 ? v : a * v + (1 - a) * prev;
    out.push(i >= n - 1 ? prev : null);
  });
  return out;
}

function emaRaw(values: number[], n: number): number[] {
  const a = 2 / (n + 1);
  const out: number[] = [];
  values.forEach((v, i) => out.push(i === 0 ? v : a * v + (1 - a) * out[i - 1]));
  return out;
}

export function sma(values: number[], n: number): Series {
  const out: Series = [];
  let sum = 0;
  values.forEach((v, i) => {
    sum += v;
    if (i >= n) sum -= values[i - n];
    out.push(i >= n - 1 ? sum / n : null);
  });
  return out;
}

export function bollinger(values: number[], n = 20, k = 2): { mid: Series; upper: Series; lower: Series } {
  const mid = sma(values, n);
  const upper: Series = [];
  const lower: Series = [];
  values.forEach((_, i) => {
    const m = mid[i];
    if (m == null) {
      upper.push(null);
      lower.push(null);
      return;
    }
    let ss = 0;
    for (let j = i - n + 1; j <= i; j++) ss += (values[j] - m) ** 2;
    const sd = Math.sqrt(ss / n);
    upper.push(m + k * sd);
    lower.push(m - k * sd);
  });
  return { mid, upper, lower };
}

export function rsi(values: number[], n = 14): Series {
  const out: Series = values.map(() => null);
  let ag = 0;
  let al = 0;
  for (let i = 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    const g = Math.max(d, 0);
    const l = Math.max(-d, 0);
    if (i === 1) {
      ag = g;
      al = l;
    } else {
      ag += (g - ag) / n;
      al += (l - al) / n;
    }
    if (i >= n) out[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  }
  return out;
}

export function macd(values: number[], fast = 12, slow = 26, signal = 9): { macd: Series; signal: Series; hist: Series } {
  const f = emaRaw(values, fast);
  const s = emaRaw(values, slow);
  const line = values.map((_, i) => f[i] - s[i]);
  const sig = emaRaw(line, signal);
  const warm = slow - 1;
  const warmSig = warm + signal - 1;
  return {
    macd: line.map((v, i) => (i >= warm ? v : null)),
    signal: sig.map((v, i) => (i >= warmSig ? v : null)),
    hist: line.map((v, i) => (i >= warmSig ? v - sig[i] : null)),
  };
}
