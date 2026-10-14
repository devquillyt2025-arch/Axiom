# Axiom

An algorithmic trading desk for **Upstox** (Indian index options): a live trading bot, charting and option-chain analysis, a backtester, trade reports, and AI trade ideas — one local app.

| | |
|---|---|
| **Frontend** | Next.js 14 (App Router) · Tailwind · shadcn/ui-style components · lightweight-charts · dark theme (`#0A0A0A`) |
| **Backend** | Python FastAPI on `127.0.0.1:8000` — Upstox REST + WebSocket, backtester, bot supervisor |
| **Bot** | Separate Python process (`python -m bot.run`), active 09:15–15:25 IST, spawned and stopped from the UI |
| **Storage** | Neon Postgres (`trades`, `bot_logs`, `backtest_results`, `suggestions`) — or a local SQLite file if `DATABASE_URL` isn't set |
| **AI** | Claude (`claude-haiku-5-5` by default) for the Suggestions tab |

> **Read [Safety & known limitations](#safety--known-limitations) before turning on live trading.** Selling options can lose far more than you collect. Paper mode is the default, and everything here ships as software, not financial advice.

---

## Quick start

Requirements: **Node 18+**, **Python 3.10+** (developed on 3.14), Git Bash/macOS/Linux shell for `start.sh` (or just use `npm run dev`).

```bash
./start.sh            # first run: creates .env, a Python venv, installs everything, then boots both servers
# or, on any OS:
npm run setup && npm run dev
```

Open **http://localhost:3000**. With no keys configured it runs on clearly-labelled **synthetic demo data** (a persistent "Demo data" badge is shown), so you can explore every screen immediately. API docs: http://127.0.0.1:8000/docs.

`./start.sh --prod` (or `npm start`) builds and serves the optimised frontend instead of the dev server. A `Procfile` is included for `honcho`/`foreman`.

> Stopping the launcher does **not** stop a running trading bot — it's its own process and keeps managing positions until 15:25 IST. Use **Stop** in the Bot tab.

### Make it real, in this order

1. **Upstox keys** → live data, the bot, AI suggestions ([setup below](#upstox-oauth-setup)).
2. **Neon** (optional) → durable trade history ([setup below](#neon-setup)).
3. **Anthropic key** → the Suggestions tab ([setup below](#claude-suggestions)).

All configuration lives in one root `.env` (see [`.env.example`](.env.example)); nothing is hardcoded anywhere.

---

## Upstox OAuth setup

1. Open the [Upstox developer apps page](https://account.upstox.com/developer/apps) and **create an app**. Upstox allows **one active API app per user** (creating a new one deletes the old).
2. Set the app's **Redirect URL** to exactly:
   ```
   http://localhost:8000/auth/callback
   ```
   (the FastAPI backend handles the callback). It must match `UPSTOX_REDIRECT_URI` in `.env` character for character.
3. Copy the **API key** and **API secret** into `.env` as `UPSTOX_API_KEY` / `UPSTOX_API_SECRET`, then restart (`Ctrl+C`, `./start.sh`).
4. In the app click **Connect Upstox** (top banner, or the Bot/Suggestions tab). You'll bounce to Upstox's login, then back to the Bot tab with "Upstox connected". The token is stored in `backend/data/token.json` (git-ignored).

**What the flow does:** `GET /auth/login` → Upstox authorization dialog (with a random single-use `state`) → `GET /auth/callback?code=…&state=…` → the backend verifies `state`, exchanges the code at `POST /v2/login/authorization/token` with your key+secret, and saves the token.

**Tokens expire daily — there is no refresh token.** Upstox access tokens die at **03:30 IST the next day**, and the standard flow issues no refresh token. Axiom detects this, shows a "session expires soon" banner, and the bot refuses to start with an expired token. You re-login (one click) each trading day. Automating login with your PIN/TOTP is deliberately not implemented — the app never stores those.

**For real orders you also need (Upstox policy, in force since April 2026 — verify current rules in your Upstox app settings):**
- A **registered static IP** for API order placement (Place/Modify/Cancel are validated against it). Market data and paper trading don't need it.
- Orders must be **LIMIT** orders — plain market orders are no longer accepted. Axiom sends *marketable limit* orders (LTP ± `ORDER_PRICE_BUFFER_PCT`).
- Algos above 10 orders/second need exchange registration (this bot is nowhere near that). `UPSTOX_ALGO_NAME` is only for if Upstox asks you to send an `X-Algo-Name` header.

## Neon setup

1. Create a project at [neon.tech](https://neon.tech), open **Connect** and copy the connection string (the pooled one, whose host contains `-pooler`, is the best fit).
2. Put it in `.env` as `DATABASE_URL=postgresql://…` and restart. Axiom creates `trades`, `bot_logs`, `backtest_results` and `suggestions` itself the first time it connects, from [`backend/migrations/0001_init.sql`](backend/migrations/0001_init.sql). The statements are idempotent, so this is safe on every start; you can also paste that file into the Neon SQL Editor yourself.
3. Check **Neon** (not "Local DB") in the top-right badge, or `GET /health` → `"store": "neon", "store_ok": true`.

Only the backend (and the bot process) ever connect to the database. The connection string stays in the backend's `.env`; the browser goes through the FastAPI `/trades` proxy.

**Optional — Neon MCP for Claude Code:** [`.mcp.json`](.mcp.json) registers Neon's hosted MCP server (`https://mcp.neon.tech/mcp`), so Claude can inspect tables, run queries and manage branches. In Claude Code run `/mcp`, pick **neon** and authorize in the browser (OAuth — no API key is stored). It can create and delete Neon projects and branches, so keep it to development; append `?readonly=true` to the URL for a read-only server.

Without `DATABASE_URL`, everything is stored in `backend/data/axiom.db` (SQLite) and the UI says so. Rows are **not** copied between the two stores when you switch.

## Claude suggestions

Set `ANTHROPIC_API_KEY` (and optionally `ANTHROPIC_MODEL`, default `claude-haiku-5-5`). On load the backend gathers Nifty/VIX/PCR/OI context, asks Claude for 2–3 option-selling setups as **schema-validated JSON** (structured outputs, low effort to keep cost down), and caches the answer for 30 minutes so reloads don't re-bill. **Regenerate** forces a fresh call. Generation is blocked on demo data.

---

## The six tabs

| Tab | What it does |
|---|---|
| **Bot** | Start/stop, paper↔live switch, strategy + parameters, live positions, today's orders (3 s refresh), risk bar (daily P&L, max drawdown, orders fired, loss-limit usage), bot activity log. Going **live requires typing `LIVE`**. |
| **Analysis** | Nifty / Bank Nifty / Sensex / Fin Nifty candlesticks with EMA 9/21/50, Bollinger, RSI and MACD toggles; option chain (strike, CE/PE LTP·OI·IV, per-strike PCR, OI bars); market-mood badge from PCR + VIX with the reasoning shown. |
| **Backtest** | Pick a registry strategy, instrument, dates, capital, lots, lot size, slippage; get an equity curve, 8 headline metrics and every trade. Saved runs reload from a dropdown. |
| **Reports** | From the `trades` table: summary cards, a P&L calendar heatmap, daily P&L bars, sortable/filterable trade history, CSV export. |
| **Suggestions** | Claude-generated setup cards (entry, SL, target, risk:reward, rationale) with the market context that was sent. Carries the "AI suggestions — not financial advice" disclaimer. |
| **Logs** | One newest-first timeline of everything you do (tab opens, bot start/stop, backtest runs, report loads, AI suggestions, Upstox login, errors) merged with the bot engine's own log lines and every order. Filter by type, level and time range (today / 7 / 30 days / all), search, expand a row for its parameters, load older entries, export CSV. Updates live every 5 s. Credentials never reach it: keys, tokens, passwords, the OAuth `code`/`state` and database URLs are masked before anything is stored. Routine polling (status, market data, this tab's own refresh) is deliberately not logged. |

## How trading works

A **strategy** looks at the underlying index and answers two questions — `should_enter(ctx)` → a BULLISH/BEARISH `Signal`, and `should_exit(ctx, position)` → a reason or nothing. The platform turns a signal into an **at-the-money option leg**:

| Option side | Bullish | Bearish |
|---|---|---|
| `SELL` (default) | sell ATM **PE** | sell ATM **CE** |
| `BUY` | buy ATM **CE** | buy ATM **PE** |

…on the nearest expiry from Upstox's option-contract API (lot size, tick size and freeze quantity come from there too). The platform — not the strategy — handles stop-loss/target (% of entry premium), the 14:45 entry cutoff, the 15:15 square-off, sizing, and the daily-loss limit. The **same strategy object** runs in the bot and in the backtester.

The bot evaluates strategies on **closed candles** (REST), checks stops/targets on **every tick** (WebSocket, with REST polling as fallback), and writes a heartbeat + state file the UI reads (`backend/data/bot_state.json`).

### Writing a strategy

Drop a file in `backend/strategies/`:

```python
from bot.strategy import Context, OpenPosition, Param, Signal, Strategy
from core.indicators import ema, crossed_above
from strategies.registry import register

@register
class MyStrategy(Strategy):
    key = "my_strategy"
    name = "My Strategy"
    description = "Shown in the UI."
    params = (Param("period", "Lookback", 20, "int", 2, 200, 1),)   # becomes a form field automatically

    def prepare(self, df):                       # vectorised + CAUSAL (never look ahead, no shift(-1))
        df = df.copy(); df["ma"] = ema(df["close"], self.p["period"]); return df

    def should_enter(self, ctx: Context):
        if ctx.i < self.min_bars(): return None
        if ctx.bar["close"] > ctx.bar["ma"] and ctx.prev["close"] <= ctx.prev["ma"]:
            return Signal("BULLISH", "Closed above MA")

    def should_exit(self, ctx: Context, pos: OpenPosition):
        if pos.direction == "BULLISH" and ctx.bar["close"] < ctx.bar["ma"]: return "Back below MA"
```

It appears in the Backtest and Bot dropdowns after an API restart. Four ship: **EMA Crossover**, **RSI Mean Reversion**, **Opening Range Breakout** and **Heikin Ashi Trend**.

**Heikin Ashi Trend** trades the candle colour: a green Heikin Ashi candle right after a red one is a bullish signal, red after green is bearish, and the position closes on the first candle of the opposite colour (so a colour change closes the old trade and opens the new one). Options: *confirm candles* (wait for 2–5 candles of the new colour) and *strong candles only* (green needs no lower wick, red no upper wick). The signals read the smoothed Heikin Ashi candles, but fills, stops and targets always use the real prices. Heikin Ashi restarts every session, so the live bot and the backtester always compute identical candles; the session's first colour is never treated as a change.

## Backtest fidelity (read this before trusting a number)

- Upstox doesn't provide historical option premiums to normal accounts, so premiums are a **Black-Scholes model** (IV = previous-day India VIX close, current expiry calendar). It captures direction, theta and vol *level*; it does **not** capture skew, bid/ask spreads or intraday IV changes. Treat results as a sanity check of the *logic*, not a P&L forecast.
- Signals are evaluated on a closed bar and **filled at the next bar's open** (no lookahead). Stops/targets are checked against bar highs/lows with the **stop assumed first** if both could hit. Positions are flattened at 15:15. The same daily-loss limit as live applies.
- Slippage (₹/unit/side) and a flat per-order charge are deducted. Live/paper `pnl` in the `trades` table is **gross** of brokerage and taxes.
- Demo-data backtests are labelled and never saved.

---

## Safety & known limitations

**What protects you by default:** `PAPER_TRADE=true` (an unparseable value aborts startup instead of going live); live needs the typed `LIVE` confirmation *and* a valid Upstox session; `MAX_LOTS=1` hard cap; `MAX_DAILY_LOSS` halts new entries and flattens (and **survives bot restarts** — it's rebuilt from today's trades); max-open-positions cap; entries only 09:20–14:45; no overnight positions; order placement is never auto-retried (a network error reconciles against the order book by tag instead); an uncertain order state disables new entries until you check. The API binds to `127.0.0.1`, validates the `Host` header, restricts CORS to the frontend origin and requires an `X-Axiom` header on every state-changing request, so other websites and other machines can't drive it.

**What you must understand before going live:**

1. **Live order and WebSocket code could not be tested against a real Upstox account** — none was available while building. It follows Upstox's published API docs and is covered by tests against fakes (request shape, fill/partial/timeout/cancel, network-error reconciliation, protobuf decoding), but the first real run is the real test. **Run paper mode for a while, then go live with 1 lot and watch the Upstox order book.**
2. **Stop-losses live in the bot, not at the exchange.** If the bot process, this PC or the internet dies while you're short options, positions are unprotected. Prefer `option_side=BUY` (defined risk) until you trust the setup, keep the machine awake, and know how to square off in the Upstox app. *Pressing Stop flattens positions* (`SQUARE_OFF_ON_STOP=true`); force-stop does not.
3. The bot needs this app running on a machine that stays on and (for live orders) has the **registered static IP**.
4. Upstox tokens expire at 03:30 IST daily — log in each trading day before starting the bot.
5. Fallback lot sizes in `backend/core/instruments.py` can go stale (exchanges revise them); live trading reads the real values from Upstox. Backtests use the fallback unless you enter a lot size.
6. Exchange holidays are detected via Upstox's market-status API while the bot runs; the backtester's expiry calendar uses *current* rules for all history.
7. This is a single-user local tool with **no login of its own**. Don't expose it to a network.

---

## Project layout

```
Axiom/
├── start.sh  Procfile  package.json  .env.example  scripts/        # one-command boot, setup, test runner
├── backend/
│   ├── main.py                       # FastAPI app: security middleware, error mapping
│   ├── api/                          # routers (auth, bot, market, data) + bot process control
│   ├── bot/
│   │   ├── auth.py                   # OAuth 2.0 + token lifecycle
│   │   ├── strategy.py               # base Strategy / Signal / Position / shared stop logic
│   │   ├── executor.py               # place / modify / cancel via Upstox v3 (paper = simulated)
│   │   ├── risk.py                   # daily-loss limit, position & lot caps, drawdown
│   │   ├── feed.py                   # Upstox WebSocket (protobuf) with reconnect + REST fallback
│   │   ├── logger.py                 # async writes to trades + bot_logs (never blocks trading)
│   │   ├── run.py                    # the bot process / main loop
│   │   └── state.py, contracts.py    # file IPC with the API; ATM contract resolution
│   ├── strategies/                   # the pluggable registry + 3 example strategies
│   ├── backtest/                     # engine + service
│   ├── core/                         # config, Upstox REST client, store (Neon/SQLite), demo data, option model, indicators, Claude client
│   ├── migrations/                   # Postgres schema (applied automatically on first connect)
│   └── tests/                        # 64 tests (+7 Postgres ones, see Development): engine mechanics, bot loop on a fake exchange, executor, stores, risk …
└── frontend/                         # Next.js app (src/app/{bot,analysis,backtest,reports,suggestions})
```

## API reference

| Method & path | Purpose |
|---|---|
| `GET /status` | Bot status, positions, risk stats, recent logs, auth + store info |
| `POST /bot/start` · `POST /bot/stop` | Start (`{strategy, symbol, lots, paper, params, confirm_live}`) / stop the bot subprocess |
| `GET /orders/today` · `GET /bot/logs` | Today's orders; bot log lines |
| `GET /market/live?symbol=NIFTY&interval=5` | LTP, day OHLC, VIX and candles |
| `GET /market/optionchain?symbol=NIFTY&expiry=` | Option chain + PCR, max pain, OI walls, mood |
| `POST /backtest` · `GET /backtest/results[/{id}]` | Run / list / load backtests |
| `GET /trades?from=&to=&instrument=&paper=` | Proxy for the `trades` table |
| `GET /strategies` · `GET /instruments` | Registry metadata (drives the UI forms) |
| `GET /suggestions?symbol=&refresh=` · `GET /suggestions/context` | Claude ideas / the context sent |
| `GET /auth/status` · `GET /auth/login` · `GET /auth/callback` · `POST /auth/logout` | OAuth |
| `GET /logs?range=&category=&level=&limit=&before=` · `POST /logs/event` | The Logs tab: merged timeline (cursor-paged by `before`) · events only the browser knows (tab opened, CSV exported) |

## Configuration reference

| Variable | Default | Notes |
|---|---|---|
| `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, `UPSTOX_REDIRECT_URI` | — / — / `http://localhost:8000/auth/callback` | OAuth app credentials |
| `DATABASE_URL` | — | Neon connection string. Optional; SQLite fallback |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | — / `claude-haiku-5-5` | Suggestions |
| `PAPER_TRADE` | `true` | Default mode (UI can override per run; live needs confirmation) |
| `MAX_DAILY_LOSS` | `5000` | ₹, realised + unrealised |
| `MAX_OPEN_POSITIONS`, `MAX_LOTS` | `1`, `1` | Hard caps |
| `SQUARE_OFF_ON_STOP` | `true` | Flatten when you press Stop |
| `ORDER_PRICE_BUFFER_PCT`, `ORDER_FILL_TIMEOUT_S`, `PAPER_SLIPPAGE_POINTS` | `1.0`, `20`, `0.5` | Execution tuning |

Frontend: set `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) in `frontend/.env.local` only if you move the API. To change ports, set `API_PORT` / `WEB_PORT` in your shell before `npm run dev` (and update `UPSTOX_REDIRECT_URI` + `FRONTEND_URL` to match).

## Development

```bash
npm test        # pyflakes + 64 backend tests + frontend typecheck + lint
cd backend && .venv/Scripts/python -m pytest -q      # (.venv/bin/python on macOS/Linux)

# Optional: also run the Postgres store tests. Use a throwaway database (a Neon branch is ideal) — never your
# real one; the tests create the tables there and delete the rows they insert.
AXIOM_TEST_DATABASE_URL="postgresql://…" .venv/Scripts/python -m pytest -q tests/test_store_postgres.py
```

## Troubleshooting

- **"Can't reach the Axiom API"** — the backend isn't running or port 8000 is taken. Check the `[api]` lines in the launcher output.
- **Login error `UDAPI100068`** — `UPSTOX_API_KEY` or the redirect URI doesn't match the app on Upstox.
- **"Not connected / session expired"** — log in again; tokens end at 03:30 IST.
- **Orders rejected / blocked** — check the registered static IP in your Upstox app and your available margin; see `backend/data/bot.log` and the Bot activity panel.
- **A trade row failed to save** — it's appended to `backend/data/failed_writes.jsonl` so nothing is lost silently. Activity-log rows that can't be stored go to `backend/data/failed_activity.jsonl` the same way.
- **Badge says "Local DB" / `store_ok: false`** — `DATABASE_URL` is empty or wrong. `GET /health` shows the database's own error (bad password, project suspended, missing `sslmode=require`…).
