import api from '@/api/client'

/** 可观测性接口封装（M3 契约 §2/§3） */

export interface CacheStats {
  HIT: number
  MISS: number
  BYPASS: number
  hit_rate: number
}

export interface SlowPath {
  path: string
  count: number
  avg_ms: number
  error_rate: number
}

export interface SlowestRequest {
  method: string
  path: string
  status: number
  elapsed_ms: number
  at: string
}

export interface MetricsSummary {
  window_minutes: number
  qps: number
  avg_ms: number
  p50_ms: number
  p95_ms: number
  p99_ms: number
  error_rate: number
  total: number
  errors: number
  cache: CacheStats
  slow_top: SlowPath[]
  slowest: SlowestRequest[]
  updated_at: string
}

export interface MetricsPoint {
  minute: string
  qps: number
  avg_ms: number
  error_rate: number
  total: number
}

export interface LogEntry {
  ts: string
  level: string
  event: string
  request_id?: string
  method?: string
  path?: string
  status?: number
  elapsed_ms?: number
  cache?: string
}

export interface LogStats {
  path?: string
  files?: number
  total_bytes?: number
  max_bytes?: number
  backup_count?: number
}

export interface LogsResult {
  list: LogEntry[]
  stats?: LogStats
}

export interface StorageStatus {
  configured?: boolean
  backend?: string
  ok?: boolean
  bucket?: string
  endpoint?: string
  degraded?: boolean
  error?: string
}

export interface SchedulerStatus {
  enabled?: boolean
  running?: boolean
  tick_seconds?: number
  last_tick_at?: string | null
  last_result?: string | null
}

export interface MailStatus {
  enabled?: boolean
  endpoint?: string
  web_ui?: string
}

export interface SystemStatus {
  db?: unknown
  cache?: unknown
  storage?: StorageStatus
  scheduler?: SchedulerStatus
  mail?: MailStatus
  logs?: LogStats
  metrics?: { window_minutes?: number; total?: number }
  uptime_seconds?: number
  checked_at?: string
}

export interface MailTestResult {
  sent: boolean
  to: string
  subject: string
  status: string
  note?: string
}

export interface TickDetail {
  task: string
  status: string
  result: string
}

export interface TickResult {
  checked: number
  due: number
  triggered: number
  failed: number
  details: TickDetail[]
}

export interface LogsQuery {
  limit?: number
  level?: string
  module?: string
  keyword?: string
}

export function fetchMetricsSummary(minutes = 60) {
  return api.get<MetricsSummary>('/metrics/summary', { minutes })
}

export function fetchMetricsTimeseries(minutes = 60) {
  return api.get<MetricsPoint[]>('/metrics/timeseries', { minutes })
}

export function fetchLogs(query: LogsQuery = {}) {
  const params: Record<string, unknown> = {}
  if (query.limit) params.limit = query.limit
  if (query.level) params.level = query.level
  if (query.module) params.module = query.module
  if (query.keyword) params.keyword = query.keyword
  return api.get<LogsResult>('/logs', params)
}

export function fetchSystemStatus() {
  return api.get<SystemStatus>('/system/status')
}

export function sendTestMail(to?: string) {
  return api.post<MailTestResult>('/mail/test', to ? { to } : {})
}

export function tickTasks() {
  return api.post<TickResult>('/tasks/tick')
}
