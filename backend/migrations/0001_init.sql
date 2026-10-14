-- Axiom schema for Neon (any Postgres 13+).
--
-- Applied automatically by the backend the first time it connects, and safe to re-run: every statement is
-- idempotent, so keep new migrations that way. You can also paste this file into the Neon SQL Editor.
--
-- Security model: only the Axiom backend connects to this database (via DATABASE_URL, which never leaves
-- the backend's .env). The browser goes through the FastAPI /trades proxy, never to the database directly.

create table if not exists public.trades (
  id            uuid primary key default gen_random_uuid(),
  created_at    timestamptz not null default now(),
  instrument    text        not null,                         -- e.g. 'NIFTY 24500 PE 20 OCT 26'
  action        text        not null check (action in ('BUY', 'SELL')),
  quantity      integer     not null check (quantity > 0),    -- units (lots x lot size)
  price         double precision not null,                    -- fill price per unit
  order_id      text,                                         -- Upstox order id(s), or PAPER-... for simulated fills
  status        text        not null,                         -- complete | partial | ...
  strategy_tag  text,
  pnl           double precision,                             -- realised P&L on CLOSING fills only (gross of charges); null on opening fills
  is_paper      boolean     not null default true,
  meta          jsonb       not null default '{}'::jsonb      -- reason, underlying, instrument_key, sl/target ...
);
create index if not exists trades_created_at_idx on public.trades (created_at desc);
create index if not exists trades_paper_created_idx on public.trades (is_paper, created_at desc);

create table if not exists public.bot_logs (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  level       text        not null,                           -- INFO | WARN | ERROR
  message     text        not null
);
create index if not exists bot_logs_created_at_idx on public.bot_logs (created_at desc);

create table if not exists public.backtest_results (
  id            uuid primary key default gen_random_uuid(),
  created_at    timestamptz not null default now(),
  strategy      text        not null,
  instrument    text        not null,
  params        jsonb,                                        -- full run config incl. strategy parameters
  metrics_json  jsonb,
  trades_json   jsonb                                         -- { trades, equity, daily_pnl }
);
create index if not exists backtest_results_created_at_idx on public.backtest_results (created_at desc);

-- Cache of Claude suggestions (avoids re-billing on every page load; 30-minute reuse window).
create table if not exists public.suggestions (
  id            uuid primary key default gen_random_uuid(),
  created_at    timestamptz not null default now(),
  symbol        text        not null,
  model         text,
  context_json  jsonb,
  setups_json   jsonb
);
create index if not exists suggestions_symbol_created_idx on public.suggestions (symbol, created_at desc);
