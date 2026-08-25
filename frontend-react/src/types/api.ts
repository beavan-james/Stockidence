/**
 * Mirrors the dicts returned by the FastAPI layer (src/stockidence/api),
 * which in turn mirrors stockidence.service models. Keep in sync when
 * the API contract evolves.
 */

export type Advice =
  | "STRONG_BUY"
  | "BUY"
  | "HOLD"
  | "SELL"
  | "STRONG_SELL";

export type RatingSource = "warehouse" | "refreshing" | "pending" | "demo";

export interface CategoryScore {
  category: string;
  score: number;
  weight: number;
}

export interface ComponentScore {
  category: string;
  component: string;
  score: number;
  weight: number;
  source: string;
}

export interface BuyPlan {
  advised_buy_price: number;
  stop_loss_price: number;
  holding_style: string;
}

export interface Rating {
  ticker: string;
  company_name: string;
  as_of: string;
  confidence_score: number;
  /** The pending placeholder response reports advice="PENDING". */
  advice: Advice | "PENDING";
  volatility_score: number;
  categories: CategoryScore[];
  components: ComponentScore[];
  buy_plan: BuyPlan | null;
  logo_url: string | null;
  fair_value: number | null;
  target_price: number | null;
  source: RatingSource;
}

export interface Suggestion {
  symbol: string;
  description: string;
  mic: string;
  type: string;
}

export interface Quote {
  price: number | null;
  high: number | null;
  low: number | null;
  open: number | null;
  prev_close: number | null;
  as_of: string | null;
}

export interface Mover {
  ticker: string;
  price: string;
  change_amount: string;
  change_percentage: string;
  volume: string;
  is_gain?: boolean;
  volume_display?: string | null;
  change_display?: string;
}

export interface Movers {
  metadata: string;
  last_updated: string;
  movers_as_of: string;
  top_gainers: Mover[];
  top_losers: Mover[];
  most_actively_traded: Mover[];
}

export interface NewsItem {
  title: string;
  url: string;
  time_published: string;
  authors: string[];
  summary: string;
  source: string;
  overall_sentiment_score: number | null;
  overall_sentiment_label: string;
  sentiment_tickers: string;
}

export interface NewsEnvelope {
  items: NewsItem[];
  total: number;
  page: number;
  page_size: number;
  page_count: number;
}

export interface ModelWeight {
  category: string;
  weight: number;
}

export interface ComponentSpecEntry {
  label: string;
  sources: string;
  direction: string;
}

export type ComponentSpec = Record<string, ComponentSpecEntry>;

export interface SeriesPoint {
  date: string;
  value: number | null;
}

export interface MacroMetric {
  label: string;
  value: number | null;
  unit: string;
  detail: string;
  as_of: string;
  series: SeriesPoint[];
  fetched: string;
}

export interface Commodity {
  label: string;
  nominal: string;
  price: number | null;
  unit: string;
  timestamp: string;
}

export interface IpoListing {
  date: string;
  exchange: string | null;
  name: string | null;
  numberOfShares: string | null;
  price: string | null;
  status: string | null;
  symbol: string | null;
  totalSharesValue: string | null;
}

export interface EarningsRelease {
  date: string;
  symbol: string;
  quarter: number | null;
  year: number | null;
  hour: string | null;
  eps_estimate: number | null;
  eps_actual: number | null;
  eps_actual_display: string | null;
  revenue_estimate: number | null;
  revenue_estimate_display: string | null;
  revenue_actual: number | null;
  revenue_actual_display: string | null;
}
