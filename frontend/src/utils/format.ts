export function fmtNum(value: number | string | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === '') return '—'
  const num = typeof value === 'string' ? Number(value) : value
  if (!Number.isFinite(num)) return '—'
  return num.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function fmtInt(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const num = typeof value === 'string' ? Number(value) : value
  if (!Number.isFinite(num)) return '—'
  return Math.round(num).toLocaleString('zh-CN')
}

export function fmtPct(value: number | string | null | undefined, digits = 1, signed = true): string {
  if (value === null || value === undefined || value === '') return '—'
  const num = typeof value === 'string' ? Number(value) : value
  if (!Number.isFinite(num)) return '—'
  const text = Math.abs(num).toFixed(digits)
  if (!signed) return `${text}%`
  return `${num > 0 ? '+' : num < 0 ? '-' : ''}${text}%`
}

export function fmtDate(value?: string | null): string {
  if (!value) return '—'
  return String(value).slice(0, 10)
}

export function fmtDateTime(value?: string | null): string {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 19)
}

export function fmtAmount(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (Math.abs(value) >= 100000000) return `${(value / 100000000).toFixed(2)} 亿`
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(2)} 万`
  return fmtInt(value)
}

export function levelTagType(level?: string): 'danger' | 'warning' | 'info' | 'success' {
  if (level === '高' || level === '一级') return 'danger'
  if (level === '中' || level === '二级') return 'warning'
  if (level === '低' || level === '三级') return 'info'
  return 'success'
}

export function alertStatusType(status?: string): 'danger' | 'warning' | 'success' | 'info' {
  if (status === '待处理') return 'danger'
  if (status === '处理中') return 'warning'
  if (status === '已关闭') return 'success'
  return 'info'
}

export function trendArrow(value?: number | null): string {
  if (value === null || value === undefined) return ''
  if (value > 0) return '↑'
  if (value < 0) return '↓'
  return '→'
}
