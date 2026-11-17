export interface UserBrief {
  id: number;
  username: string;
  display_name: string;
  role_key: string;
  role_name: string;
  org?: string;
}

export interface LoginResult {
  token: string;
  expires_in: number;
  user: UserBrief;
  permissions: string[];
}

export interface MeResult {
  user: UserBrief;
  permissions: string[];
}

export interface DictOption {
  id: number;
  code: string;
  name: string;
  category?: string;
  unit?: string;
}

export interface MetaDicts {
  varieties: DictOption[];
  regions: DictOption[];
  markets: DictOption[];
  market_types: string[];
  alert_levels: string[];
  report_types: { key: string; name: string }[];
  roles: { key: string; name: string }[];
}

export interface DashboardKpi {
  variety_count: number;
  region_count: number;
  market_count: number;
  record_count: number;
  avg_price: number;
  yoy_pct: number;
  alert_open: number;
  alert_today: number;
  avg_mape: number;
  direction_acc: number;
  completeness: number;
}

export interface DashboardSummary {
  kpi: DashboardKpi;
  latest_price_date: string;
  last_forecast_at: string;
  updated_at: string;
}

export interface TrendData {
  dates: string[];
  series: { name: string; values: number[] }[];
  unit: string;
  latest?: number;
}

export interface PriceRow {
  id: number;
  date: string;
  variety: string;
  region: string;
  market: string;
  market_type: string;
  price: number;
  min_price: number;
  max_price: number;
  volume: number;
  unit: string;
  quality_flag: string;
}

export interface PriceStats {
  avg_price?: number;
  max_price?: number;
  min_price?: number;
  volatility?: number;
  record_count?: number;
  [key: string]: number | undefined;
}

export interface ForecastPoint {
  target_date: string;
  point: number;
  lower: number;
  upper: number;
  confidence: number;
  direction: string;
}

export interface ForecastResult {
  forecast_id: number;
  model: { key: string; name: string; mape: number; direction_acc: number };
  history: { dates: string[]; values: number[] };
  forecast: ForecastPoint[];
  summary: {
    expected_change_pct: number;
    trend: string;
    risk_level: string;
    confidence_level: string;
    text: string;
  };
  explain: { factor: string; contribution: number; description: string }[];
  created_at: string;
  unit?: string;
}

export interface AlertRow {
  id: number;
  level: string;
  title: string;
  detail?: string;
  status: string;
  alert_date: string;
  variety?: string;
  region?: string;
  handler?: string;
  handled_at?: string;
  handle_note?: string;
}

export interface AlertStatistics {
  open_count: number;
  total_30d: number;
  by_level: { level: string; count: number }[];
  by_status: { status: string; count: number }[];
  recall_rate: number;
  false_positive_rate: number;
}

export interface PageData<T> {
  list: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface NotificationRow {
  id: number;
  title: string;
  content: string;
  category: string;
  level: string;
  link?: string;
  is_read: boolean;
  created_at: string;
}

export interface NotificationSummary {
  total: number;
  unread: number;
}
