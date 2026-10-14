"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, ChartCandlestick, ChartColumn, FlaskConical, PlugZap, ScrollText, Sparkles } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LOGIN_URL, ApiError, logEvent } from "@/lib/api";
import { useStatus } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/bot", label: "Bot", icon: Bot },
  { href: "/analysis", label: "Analysis", icon: ChartCandlestick },
  { href: "/backtest", label: "Backtest", icon: FlaskConical },
  { href: "/reports", label: "Reports", icon: ChartColumn },
  { href: "/suggestions", label: "Suggestions", icon: Sparkles },
  { href: "/logs", label: "Logs", icon: ScrollText },
] as const;

function Logo() {
  return (
    <Link href="/bot" className="flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="8" fill="hsl(var(--primary))" />
        <path d="M9 21V13M9 11V9M16 24V16M16 14v-3M23 19V12M23 10V8" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
        <rect x="7" y="13" width="4" height="8" rx="1" fill="#fff" />
        <rect x="14" y="16" width="4" height="8" rx="1" fill="#fff" fillOpacity=".55" />
        <rect x="21" y="12" width="4" height="7" rx="1" fill="#fff" />
      </svg>
      <span className="text-base font-semibold tracking-tight">Axiom</span>
    </Link>
  );
}

function SessionChips() {
  const { data, error } = useStatus(5000);
  const auth = data?.auth;
  if (!data && error) return <Badge variant="loss">API offline</Badge>;
  if (!auth) return null;
  return (
    <div className="flex items-center gap-2">
      {auth.authenticated ? (
        <Badge variant="profit" title={`Signed in as ${auth.user_name || auth.user_id}`}>
          <span className="size-1.5 animate-pulse-dot rounded-full bg-profit" aria-hidden />
          Upstox live
        </Badge>
      ) : (
        <Badge variant="warn">Demo data</Badge>
      )}
      <Badge variant="muted" className="hidden lg:inline-flex" title={data.store === "neon" ? "Trades are stored in Neon" : "Neon isn't configured — using a local SQLite file"}>
        {data.store === "neon" ? "Neon" : "Local DB"}
      </Badge>
    </div>
  );
}

function Banners() {
  const { data, error } = useStatus(5000);
  if (!data && error) {
    return (
      <Alert variant="error" title="Can't reach the Axiom API">
        {error instanceof ApiError ? error.message : "Start the backend (see README) and reload."}
      </Alert>
    );
  }
  if (data && !data.auth.authenticated) {
    return (
      <Alert
        variant="warn"
        title="Showing synthetic demo data"
        action={
          data.auth.configured ? (
            <Button asChild size="sm">
              <a href={LOGIN_URL}>
                <PlugZap /> Connect Upstox
              </a>
            </Button>
          ) : undefined
        }
      >
        {data.auth.configured
          ? "Prices, option chains and backtests below are generated, not real. Connect Upstox for live data, the bot and AI suggestions."
          : "Add UPSTOX_API_KEY, UPSTOX_API_SECRET and UPSTOX_REDIRECT_URI to .env, restart the API, then connect (README → Upstox OAuth)."}
      </Alert>
    );
  }
  if (data && data.auth.authenticated && data.auth.expires_in_s != null && data.auth.expires_in_s < 3600 && data.auth.source === "oauth") {
    return (
      <Alert
        variant="info"
        title="Your Upstox session expires soon"
        action={
          <Button asChild size="sm" variant="outline">
            <a href={LOGIN_URL}>Re-login</a>
          </Button>
        }
      >
        Upstox tokens end at 03:30 IST daily and can&apos;t be refreshed silently — log in again before it lapses.
      </Alert>
    );
  }
  return null;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  // Feed the Logs tab. The Logs tab itself isn't logged (it would add a row to the very list being read), and the
  // 2s guard absorbs React dev-mode double effects and quick re-clicks.
  const lastNav = useRef<{ path: string; at: number } | null>(null);
  useEffect(() => {
    const item = NAV.find((n) => pathname.startsWith(n.href));
    if (!item || item.href === "/logs") return;
    const now = Date.now();
    if (lastNav.current && lastNav.current.path === pathname && now - lastNav.current.at < 2000) return;
    lastNav.current = { path: pathname, at: now };
    logEvent("navigation", "view", `Opened ${item.label}`, { path: pathname });
  }, [pathname]);

  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[100] focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground">
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b bg-background/95">
        <div className="container flex h-14 items-center gap-4">
          <Logo />
          <nav aria-label="Primary" className="ml-4 hidden h-full items-stretch gap-1 md:flex">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "relative flex items-center gap-2 px-3 text-[13px] font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                    active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Icon className="size-4" aria-hidden />
                  {label}
                  {active && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" aria-hidden />}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto">
            <SessionChips />
          </div>
        </div>
      </header>

      <main id="main" className="container flex-1 space-y-4 py-4 pb-28 md:space-y-5 md:py-6 md:pb-10">
        <Banners />
        {children}
      </main>

      <nav
        aria-label="Primary"
        className="fixed inset-x-0 bottom-0 z-40 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        <ul className="grid grid-cols-6">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                    active ? "text-info" : "text-muted-foreground",
                  )}
                >
                  <Icon className="size-5" aria-hidden />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
