// Mirrors the FastAPI payloads (backend/api/*, core/marketdata.py). Keep in sync when the API changes.

export type DataSource = "upstox" | "demo";
export type OptionSide = "SELL" | "BUY";

export interface AuthStatus {
  configured: boolean;
  authenticated: boolean;
  user_name: string;
  user_id: string;
  expires_at: string | null;
  expires_in_s: number | null;
  source: string | null;
}

export interface Position {
  id: string;
  strategy: string;
  underlying: string;
  instrument: string;
  instrument_key: string;
  option_type: "CE" | "PE";
  strike: number;
  expiry: string;
  side: OptionSide;
  qty: number;
  lot_size: number;
  avg_price: number;
  ltp: number;
  pnl: number;
  sl: number | null;
  target: number | null;
  direction: "BULLISH" | "BEARISH";
  entry_time: string;
  reason: string;
}

export interface RiskStats {
  daily_pnl: number;
  realized: number;
  unrealized: number;
  max_drawdown: number;
  orders_fired: number;
  halted: boolean;
  halt_reason: string;
  max_daily_loss: number;
  max_open_positions: number;
  max_lots: number;
}

export type BotStatusName = "idle" | "starting" | "waiting" | "running" | "stopping" | "stopped" | "error" | "crashed";

export interface BotInfo {
  status: BotStatusName;
  running: boolean;
  message: string;
  mode: "paper" | "live" | null;
  strategy: string | null;
  strategy_name: string | null;
  symbol: string | null;
  lots: number | null;
  params: Record<string, number | string> | null;
  started_at: string | null;
  spot: number | null;
  vix: number | null;
  last_signal: { time: string; direction: string; reason: string } | null;
  feed_connected: boolean;
  heartbeat_age_s: number | null;
}

export interface LogLine {
  created_at: string;
  level: "INFO" | "WARN" | "ERROR" | string;
  message: string;
}

export type LogCategory = "all" | "navigation" | "bot" | "engine" | "trade" | "backtest" | "reports" | "suggestions" | "auth" | "system";
export type LogRange = "today" | "7d" | "30d" | "all";
export type LogLevel = "all" | "INFO" | "WARN" | "ERROR";

/** One row of the Logs tab: something you did, something the bot engine said, or an order. */
export interface LogEntry {
  id: string;
  created_at: string;
  source: "activity" | "bot" | "trade";
  category: string;
  action: string;
  level: "INFO" | "WARN" | "ERROR" | string;
  summary: string;
  details: Record<string, unknown> | null;
}

export interface LogsResponse {
  entries: LogEntry[];
  next_before: string | null;
  range: LogRange;
  category: LogCategory;
  level: LogLevel;
  store: "neon" | "sqlite";
}

export interface StatusResponse {
  bot: BotInfo;
  positions: Position[];
  risk: RiskStats | null;
  logs: LogLine[];
  settings: {
    paper_default: boolean;
    max_daily_loss: number;
    max_open_positions: number;
    max_lots: number;
    square_off_on_stop: boolean;
  };
  auth: AuthStatus;
  store: "neon" | "sqlite";
  market_open: boolean;
  server_time: string;
}

export interface Trade {
  id: string;
  created_at: string;
  date: string;
  instrument: string;
  underlying: string;
  action: "BUY" | "SELL";
  quantity: number;
  price: number;
  order_id: string | null;
  status: string;
  strategy_tag: string | null;
  pnl: number | null;
  is_paper: boolean;
  reason: string | null;
}

export interface OrdersToday {
  orders: Trade[];
  summary: { orders: number; closed_trades: number; realized_pnl: number; wins: number; losses: number };
  as_of: string;
}

export interface TradesResponse {
  store: "neon" | "sqlite";
  from: string;
  to: string;
  count: number;
  trades: Trade[];
}

export interface StrategyParam {
  key: string;
  label: string;
  default: number | string;
  kind: "int" | "float" | "select";
  min: number | null;
  max: number | null;
  step: number | null;
  options: (number | string)[];
  help: string;
}

export interface StrategyInfo {
  key: string;
  name: string;
  description: string;
  warmup_bars: number;
  params: StrategyParam[];
}

export interface Instrument {
  symbol: string;
  name: string;
  lot_size: number;
  strike_step: number;
}

export interface Candle {
  time: number; // UTC-shifted seconds so the chart axis reads in IST
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface LiveSnapshot {
  symbol: string;
  name: string;
  source: DataSource;
  market_open: boolean;
  session_date: string;
  ltp: number;
  prev_close: number;
  change: number;
  change_pct: number;
  ohlc: { open: number; high: number; low: number; close: number; volume: number };
  vix: number | null;
  interval: number;
  as_of: string;
  candles: Candle[];
}

export interface ChainLeg {
  key: string | null;
  ltp: number;
  oi: number;
  oi_change: number;
  volume: number;
  iv: number;
  delta: number;
}

export interface ChainRow {
  strike: number;
  ce: ChainLeg;
  pe: ChainLeg;
  pcr: number | null;
}

export interface Mood {
  label: "Bullish" | "Bearish" | "Neutral";
  score: number;
  pcr: number | null;
  vix: number | null;
  reasons: string[];
}

export interface OptionChain {
  symbol: string;
  source: DataSource;
  expiry: string;
  expiries: string[];
  spot: number;
  vix: number | null;
  atm: number;
  pcr: number | null;
  total_ce_oi: number;
  total_pe_oi: number;
  max_pain: number | null;
  resistance: number | null;
  support: number | null;
  mood: Mood;
  rows: ChainRow[];
  as_of: string;
}

export interface BacktestRequest {
  strategy: string;
  symbol: string;
  start: string;
  end: string;
  capital: number;
  lots: number;
  lot_size?: number | null;
  slippage: number;
  charges_per_order: number;
  params: Record<string, number | string>;
}

export interface BacktestMetrics {
  total_pnl: number;
  return_pct: number;
  final_equity: number;
  total_trades: number;
  win_rate: number | null;
  max_drawdown: number;
  max_drawdown_pct: number;
  sharpe: number | null;
  avg_profit: number | null;
  avg_loss: number | null;
  rr_ratio: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  best_day: number | null;
  worst_day: number | null;
  trading_days: number;
  avg_duration_min: number | null;
}

export interface BacktestTrade {
  n: number;
  date: string;
  instrument: string;
  side: OptionSide;
  direction: string;
  entry_time: string;
  exit_time: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  gross_pnl: number;
  charges: number;
  pnl: number;
  duration_min: number;
  exit_reason: string;
  signal_reason: string;
}

export interface BacktestResult {
  id: string | null;
  data_source: DataSource;
  config: {
    strategy: string;
    strategy_name?: string;
    symbol: string;
    start: string;
    end: string;
    params: Record<string, number | string>;
    capital: number;
    lots: number;
    lot_size: number;
    qty?: number;
    slippage: number;
    charges_per_order?: number;
  };
  metrics: BacktestMetrics;
  equity: { time: number; value: number }[];
  daily_pnl: { date: string; pnl: number }[];
  trades: BacktestTrade[];
  model: string;
  created_at?: string;
}

export interface BacktestListItem {
  id: string;
  created_at: string;
  strategy: string;
  instrument: string;
  config: BacktestResult["config"];
  metrics: BacktestMetrics;
}

export interface Setup {
  name: string;
  strategy_type: string;
  bias: "Bullish" | "Bearish" | "Neutral";
  entry_zone: string;
  stop_loss: string;
  target: string;
  risk_reward: string;
  rationale: string;
}

export interface SuggestionsResponse {
  summary: string;
  setups: Setup[];
  context: Record<string, unknown>;
  generated_at: string;
  model: string;
  cached: boolean;
}
