const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** ₹1,23,456 */
export function rupees(n: number | null | undefined, dp = 0): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n < 0 ? "-" : ""}₹${(dp ? inr2 : inr0).format(Math.abs(n))}`;
}

/** +₹1,234 / -₹1,234 — always signed so P&L never relies on color alone. */
export function signedRupees(n: number | null | undefined, dp = 0): string {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}₹${(dp ? inr2 : inr0).format(Math.abs(n))}`;
}

export function price(n: number | null | undefined, dp = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp }).format(n);
}

export function int(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return inr0.format(n);
}

/** 12.3L / 4.56Cr — how Indian traders read open interest. */
export function compactIN(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const a = Math.abs(n);
  const s = n < 0 ? "-" : "";
  if (a >= 1e7) return `${s}${(a / 1e7).toFixed(2)}Cr`;
  if (a >= 1e5) return `${s}${(a / 1e5).toFixed(2)}L`;
  if (a >= 1e3) return `${s}${(a / 1e3).toFixed(1)}K`;
  return `${s}${a.toFixed(0)}`;
}

export function pct(n: number | null | undefined, dp = 2, signed = false): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${signed && n > 0 ? "+" : ""}${n.toFixed(dp)}%`;
}

export type Tone = "profit" | "loss" | "neutral";
export function tone(n: number | null | undefined): Tone {
  if (n == null || n === 0 || Number.isNaN(n)) return "neutral";
  return n > 0 ? "profit" : "loss";
}
export const toneClass: Record<Tone, string> = {
  profit: "text-profit",
  loss: "text-loss",
  neutral: "text-foreground",
};

export function timeIST(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
}
export function dateTimeIST(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata",
  });
}
/** 14 Oct, 18:31:07 — the Logs tab needs seconds, and the date because it spans days. */
export function dateTimeSecIST(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: "Asia/Kolkata",
  });
}
export function dateShort(iso: string): string {
  return new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" });
}

export function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
export function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDate(d);
}

export function formatDuration(mins: number | null | undefined): string {
  if (mins == null) return "—";
  if (mins < 60) return `${Math.round(mins)}m`;
  return `${Math.floor(mins / 60)}h ${Math.round(mins % 60)}m`;
}
