export interface UserBrief {
  id: number
  username: string
  display_name: string
  role_key: string
  role_name?: string
  org?: string
  phone?: string
  email?: string
  status?: string
  last_login_at?: string
}

export interface LoginResult {
  token: string
  expires_in: number
  user: UserBrief
  permissions: string[]
}

export interface MenuNode {
  key: string
  title: string
  path: string
  icon?: string
  permission?: string
  children?: MenuNode[]
}

export interface DictOption {
  id: number
  code?: string
  name: string
  category?: string
  unit?: string
}

export interface MetaDicts {
  varieties: DictOption[]
  regions: DictOption[]
  markets: Array<DictOption & { region_code?: string; market_type?: string }>
  market_types: string[]
  alert_levels: string[]
  report_types: Array<{ key: string; name: string }>
  roles: Array<{ key: string; name: string }>
}

export interface PriceRow {
  id: number
  variety: string
  region: string
  market?: string
  market_type: string
  price_date: string
  price: number
  min_price?: number
  max_price?: number
  volume?: number
  unit: string
  quality_flag: string
  yoy_pct?: number
  mom_pct?: number
}

export interface ForecastPoint {
  target_date: string
  point: number
  lower: number
  upper: number
  confidence: number
  direction: string
}

export interface ForecastRunResult {
  forecast_id: number
  model: { key: string; name: string; mape: number; direction_acc: number }
  history: { dates: string[]; values: number[] }
  forecast: ForecastPoint[]
  summary: {
    expected_change_pct: number
    trend: string
    risk_level: string
    confidence_level: string
    text: string
  }
  explain: Array<{ factor: string; contribution: number; description: string }>
  created_at: string
}

export interface AlertRow {
  id: number
  level: string
  title: string
  variety: string
  region: string
  alert_date: string
  status: string
  rule_name?: string
  detail?: string
  handler?: string
  handled_at?: string
  handle_note?: string
  notify_channel?: string
}

export interface ReportRow {
  id: number
  title: string
  report_type: string
  period_start: string
  period_end: string
  status: string
  summary?: string
  created_by?: string
  created_at: string
}
