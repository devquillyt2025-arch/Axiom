import { TrendingDown, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { signedRupees, tone, toneClass } from "@/lib/format";

/** A P&L figure: signed text + arrow icon + colour (so it's readable without colour vision). */
export function Pnl({ value, className, dp = 0, icon = true }: { value: number | null | undefined; className?: string; dp?: number; icon?: boolean }) {
  const t = tone(value);
  return (
    <span className={cn("num inline-flex items-center gap-1", toneClass[t], className)}>
      {icon && t === "profit" && <TrendingUp className="size-3.5 shrink-0" aria-hidden />}
      {icon && t === "loss" && <TrendingDown className="size-3.5 shrink-0" aria-hidden />}
      {signedRupees(value, dp)}
    </span>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone: valueTone,
  className,
  loading,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "profit" | "loss" | "neutral";
  className?: string;
  /** Placeholder while data loads: same markup (so exactly the same height as the real tile), text hidden. */
  loading?: boolean;
}) {
  return (
    <div
      aria-hidden={loading || undefined}
      className={cn("min-w-0 rounded-lg border bg-card p-3 md:p-4", loading && "animate-pulse select-none [&_*]:text-transparent", className)}
    >
      <p className="label-xs truncate">{label}</p>
      <p className={cn("num mt-1.5 truncate text-lg font-semibold leading-none md:text-xl", valueTone && toneClass[valueTone])}>{value}</p>
      {sub != null && <p className="mt-1.5 text-xs leading-4 text-muted-foreground">{sub}</p>}
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon?: React.ReactNode; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
      {icon && <div className="text-muted-foreground/70 [&>svg]:size-8">{icon}</div>}
      <p className="text-sm font-medium">{title}</p>
      {children && <p className="max-w-md text-[13px] text-muted-foreground">{children}</p>}
    </div>
  );
}
