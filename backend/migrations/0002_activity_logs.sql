-- Activity log: a record of what was done in Axiom and what happened (bot start/stop, backtests, logins,
-- report loads, errors, tab navigation ...). Idempotent, like every migration here.

create table if not exists public.activity_logs (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  category    text        not null,                           -- navigation | bot | backtest | reports | suggestions | auth | system
  action      text        not null,                           -- short machine-friendly verb, e.g. start, run, trades_query
  summary     text        not null,                           -- the one-line human description shown in the Logs tab
  level       text        not null default 'INFO',            -- INFO | WARN | ERROR
  details     jsonb                                           -- request parameters / results, secrets redacted before storing
);
create index if not exists activity_logs_created_at_idx on public.activity_logs (created_at desc);
create index if not exists activity_logs_category_created_idx on public.activity_logs (category, created_at desc);
