"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { StrategyParam } from "@/lib/types";

export type ParamValues = Record<string, number | string>;

export function defaultsFor(params: StrategyParam[]): ParamValues {
  return Object.fromEntries(params.map((p) => [p.key, p.default]));
}

/** Renders a strategy's declared parameters (from the Python registry) as form fields. */
export function ParamFields({
  params,
  values,
  onChange,
  disabled,
  idPrefix,
}: {
  params: StrategyParam[];
  values: ParamValues;
  onChange: (next: ParamValues) => void;
  disabled?: boolean;
  idPrefix: string;
}) {
  const set = (k: string, v: number | string) => onChange({ ...values, [k]: v });
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {params.map((p) => {
        const id = `${idPrefix}-${p.key}`;
        const v = values[p.key] ?? p.default;
        return (
          <div key={p.key} className="space-y-1.5">
            <Label htmlFor={id}>{p.label}</Label>
            {p.kind === "select" ? (
              <Select value={String(v)} onValueChange={(s) => set(p.key, typeof p.options[0] === "number" ? Number(s) : s)} disabled={disabled}>
                <SelectTrigger id={id}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {p.options.map((o) => (
                    <SelectItem key={String(o)} value={String(o)}>
                      {String(o)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input
                id={id}
                type="number"
                inputMode="decimal"
                min={p.min ?? undefined}
                max={p.max ?? undefined}
                step={p.step ?? (p.kind === "int" ? 1 : "any")}
                value={v}
                disabled={disabled}
                onChange={(e) => set(p.key, e.target.value === "" ? "" : Number(e.target.value))}
              />
            )}
            {p.help && <p className="text-xs leading-4 text-muted-foreground">{p.help}</p>}
          </div>
        );
      })}
    </div>
  );
}
