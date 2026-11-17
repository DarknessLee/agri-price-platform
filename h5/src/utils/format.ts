import dayjs from 'dayjs';

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toFixed(digits);
}

export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toLocaleString('zh-CN');
}

export function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  const num = Number(value);
  const sign = num > 0 ? '+' : '';
  return `${sign}${num.toFixed(digits)}%`;
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return '-';
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format('YYYY-MM-DD') : String(value);
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return '-';
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm') : String(value);
}

export function shortDate(value: string): string {
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format('MM-DD') : value;
}

export function trendClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return '';
  if (Number(value) > 0) return 'h5-up';
  if (Number(value) < 0) return 'h5-down';
  return '';
}

export function today(): string {
  return dayjs().format('YYYY年MM月DD日');
}

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

export function weekday(): string {
  return WEEKDAYS[dayjs().day()];
}

export function levelTag(level: string): 'danger' | 'warning' | 'primary' | 'default' {
  if (level === '高') return 'danger';
  if (level === '中') return 'warning';
  if (level === '低') return 'primary';
  return 'default';
}

export function alertStatusText(status: string): string {
  if (status === '待处理') return '待处理';
  if (status === '处理中') return '处理中';
  if (status === '已关闭') return '已关闭';
  return status;
}
