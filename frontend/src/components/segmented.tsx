"use client";

import { cn } from "@/lib/utils";

interface Option<T extends string | number> {
  value: T;
  label: React.ReactNode;
}

/** Pill-style single-choice control (radiogroup semantics). Used for instrument + timeframe pickers. */
export function Segmented<T extends string | number>({
  value,
  onChange,
  options,
  label,
  className,
  disabled,
}: {
  value: T;
  onChange: (v: T) => void;
  options: Option<T>[];
  label: string;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("inline-flex max-w-full overflow-x-auto rounded-lg border bg-muted/40 p-0.5", className)}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={String(o.value)}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            className={cn(
              "h-10 min-w-11 shrink-0 cursor-pointer whitespace-nowrap rounded-md px-3 text-[13px] font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 md:h-8",
              active ? "bg-secondary text-foreground shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Toggle button for indicator overlays (aria-pressed). */
export function ToggleChip({
  pressed,
  onToggle,
  children,
  swatch,
}: {
  pressed: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  swatch?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onToggle}
      className={cn(
        "inline-flex h-10 cursor-pointer items-center gap-2 rounded-md border px-3 text-[13px] font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:h-8",
        pressed ? "border-primary/60 bg-primary/15 text-foreground" : "border-input text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      {swatch && <span className="size-2.5 rounded-full" style={{ background: swatch, opacity: pressed ? 1 : 0.45 }} aria-hidden />}
      {children}
    </button>
  );
}
