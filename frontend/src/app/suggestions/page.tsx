"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { Bot, PlugZap, RefreshCw, Sparkles, Target, ShieldAlert, Crosshair, Scale } from "lucide-react";
import { Segmented } from "@/components/segmented";
import { Stat } from "@/components/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, LOGIN_URL, api, errorMessage } from "@/lib/api";
import { compactIN, dateTimeIST, int, price } from "@/lib/format";
import { useApi, useStatus } from "@/lib/hooks";
import type { Setup, SuggestionsResponse } from "@/lib/types";

const SYMBOLS = [
  { value: "NIFTY", label: "Nifty 50" },
  { value: "BANKNIFTY", label: "Bank Nifty" },
  { value: "SENSEX", label: "Sensex" },
  { value: "FINNIFTY", label: "Fin Nifty" },
];

type Ctx = {
  spot?: number; change_pct?: number; india_vix?: number | null; pcr?: number | null; expiry?: string; days_to_expiry?: number;
  atm_strike?: number; atm_straddle_premium?: number | null; max_pain?: number | null; mood_heuristic?: string;
  top_call_oi_strikes?: { strike: number; oi: number }[]; top_put_oi_strikes?: { strike: number; oi: number }[];
};

const biasVariant = { Bullish: "profit", Bearish: "loss", Neutral: "muted" } as const;

function SetupCard({ s, index }: { s: Setup; index: number }) {
  const rows = [
    { icon: Crosshair, label: "Entry zone", value: s.entry_zone },
    { icon: ShieldAlert, label: "Stop-loss", value: s.stop_loss, tone: "text-loss" },
    { icon: Target, label: "Target", value: s.target, tone: "text-profit" },
    { icon: Scale, label: "Risk : Reward", value: s.risk_reward },
  ];
  return (
    <Card className="flex flex-col">
      <CardHeader className="gap-2">
        <div className="flex items-center justify-between gap-2">
          <span className="label-xs">Setup {index + 1}</span>
          <Badge variant={biasVariant[s.bias]}>{s.bias}</Badge>
        </div>
        <CardTitle className="text-base leading-snug">{s.name}</CardTitle>
        <div>
          <Badge variant="outline">{s.strategy_type}</Badge>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        <dl className="space-y-3">
          {rows.map(({ icon: Icon, label, value, tone }) => (
            <div key={label} className="grid grid-cols-[1.25rem_1fr] gap-x-2">
              <Icon className={`mt-0.5 size-4 ${tone ?? "text-muted-foreground"}`} aria-hidden />
              <div>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="text-[13px] leading-5">{value}</dd>
              </div>
            </div>
          ))}
        </dl>
        <div className="mt-auto border-t pt-3">
          <p className="label-xs mb-1">Rationale</p>
          <p className="text-[13px] leading-5 text-muted-foreground">{s.rationale}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export default function SuggestionsPage() {
  const { mutate } = useSWRConfig();
  const [symbol, setSymbol] = useState("NIFTY");
  const key = `/suggestions?symbol=${symbol}`;
  const { data: status } = useStatus(5000);
  const connected = status?.auth.authenticated ?? null; // null until the first status response
  // Don't call the endpoint at all without a session (it would just 409) or before we know.
  const { data, error: fetchError, isLoading } = useApi<SuggestionsResponse>(connected ? key : null, { shouldRetryOnError: false });
  const error = connected === false ? new ApiError(409, "Connect Upstox first.") : fetchError;
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const refresh = async () => {
    setRefreshing(true);
    setRefreshError(null);
    try {
      const fresh = await api.get<SuggestionsResponse>(`${key}&refresh=true`);
      await mutate(key, fresh, { revalidate: false });
    } catch (e) {
      setRefreshError(errorMessage(e));
    } finally {
      setRefreshing(false);
    }
  };

  const ctx = (data?.context ?? {}) as Ctx;
  const busy = isLoading || refreshing;
  const needsLogin = error instanceof ApiError && error.status === 409;
  const noKey = error instanceof ApiError && error.status === 503;

  return (
    <div className="space-y-4 md:space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Sparkles className="size-5 text-info" aria-hidden />
          <h1 className="page-title">Suggestions</h1>
        </div>
        <Button onClick={refresh} loading={refreshing} disabled={isLoading || needsLogin || noKey}>
          <RefreshCw /> Regenerate
        </Button>
      </div>

      <Segmented label="Instrument" value={symbol} onChange={setSymbol} options={SYMBOLS} />

      <Alert variant="warn" title="AI suggestions — not financial advice">
        Ideas generated by a language model from the market snapshot below. They can be wrong, stale within minutes, or unsuitable for your risk. Study them; don&apos;t copy them blindly. Selling options can lose far more than the premium collected.
      </Alert>

      {needsLogin && (
        <Alert
          variant="info"
          title="Connect Upstox to generate suggestions"
          action={
            status?.auth.configured ? (
              <Button asChild size="sm">
                <a href={LOGIN_URL}>
                  <PlugZap /> Connect
                </a>
              </Button>
            ) : undefined
          }
        >
          Suggestions use live Nifty, VIX and option-chain data, which needs an Upstox session.
          {status?.auth.configured === false && " Add your Upstox API keys to .env first (see the README)."}
        </Alert>
      )}
      {noKey && <Alert variant="info" title="Claude API key missing">{error?.message}</Alert>}
      {error && !needsLogin && !noKey && (
        <Alert variant="error" title="Couldn't generate suggestions" action={<Button size="sm" variant="outline" onClick={refresh}>Retry</Button>}>
          {error.message}
        </Alert>
      )}
      {refreshError && <Alert variant="error" title="Regenerate failed">{refreshError}</Alert>}

      {busy && !data && (
        <div className="space-y-4">
          <p className="flex items-center gap-2 text-[13px] text-muted-foreground" role="status">
            <Bot className="size-4 animate-pulse" aria-hidden /> Reading the market and asking Claude — this takes 5–15 seconds…
          </p>
          <div className="grid gap-4 md:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-80" />
            ))}
          </div>
        </div>
      )}

      {data && (
        <>
          <section aria-label="Market context sent to Claude" className="space-y-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-sm font-semibold">Market context</h2>
              <p className="text-xs text-muted-foreground">
                Generated {dateTimeIST(data.generated_at)} IST · {data.model}
                {data.cached ? " · cached (under 30 min old)" : ""}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
              <Stat label="Spot" value={ctx.spot != null ? price(ctx.spot) : "—"} sub={ctx.change_pct != null ? `${ctx.change_pct >= 0 ? "+" : ""}${ctx.change_pct}% today` : undefined} />
              <Stat label="India VIX" value={ctx.india_vix != null ? ctx.india_vix.toFixed(2) : "—"} />
              <Stat label="PCR" value={ctx.pcr != null ? ctx.pcr.toFixed(2) : "—"} sub={ctx.mood_heuristic ? `Mood: ${ctx.mood_heuristic}` : undefined} />
              <Stat label="Expiry" value={ctx.expiry ?? "—"} sub={ctx.days_to_expiry != null ? `${ctx.days_to_expiry} day${ctx.days_to_expiry === 1 ? "" : "s"} left` : undefined} />
              <Stat label="ATM straddle" value={ctx.atm_straddle_premium != null ? price(ctx.atm_straddle_premium) : "—"} sub={ctx.atm_strike != null ? `Strike ${int(ctx.atm_strike)}` : undefined} />
              <Stat label="Max pain" value={ctx.max_pain != null ? int(ctx.max_pain) : "—"} />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {(
                [
                  ["Top call OI strikes (resistance)", ctx.top_call_oi_strikes, "text-loss"],
                  ["Top put OI strikes (support)", ctx.top_put_oi_strikes, "text-profit"],
                ] as const
              ).map(([title, list, tone]) => (
                <div key={title} className="rounded-lg border bg-card p-3">
                  <p className="label-xs">{title}</p>
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {(list ?? []).map((o) => (
                      <li key={o.strike} className="num rounded-md border px-2.5 py-1 text-[13px]">
                        <span className={tone}>{int(o.strike)}</span> <span className="text-muted-foreground">· {compactIN(o.oi)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>

          <Card>
            <CardHeader>
              <CardTitle>Today&apos;s read</CardTitle>
              <CardDescription className="text-[13px] leading-5 text-foreground/90">{data.summary}</CardDescription>
            </CardHeader>
          </Card>

          <div className={`grid gap-4 md:grid-cols-2 xl:grid-cols-3 ${refreshing ? "opacity-60" : ""}`} aria-busy={refreshing}>
            {data.setups.map((s, i) => (
              <SetupCard key={`${s.name}-${i}`} s={s} index={i} />
            ))}
          </div>
          <p className="text-center text-xs text-muted-foreground">AI suggestions — not financial advice.</p>
        </>
      )}
    </div>
  );
}
