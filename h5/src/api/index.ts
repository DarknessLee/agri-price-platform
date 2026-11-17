import { api } from './client';
import type {
  AlertRow,
  AlertStatistics,
  DashboardSummary,
  ForecastResult,
  LoginResult,
  MeResult,
  MetaDicts,
  NotificationRow,
  NotificationSummary,
  PageData,
  PriceRow,
  PriceStats,
  TrendData,
} from '@/types';

export const authApi = {
  login: (username: string, password: string) =>
    api.post<LoginResult>('/auth/login', { username, password }),
  me: () => api.get<MeResult>('/auth/me'),
  logout: () => api.post<null>('/auth/logout'),
  changePassword: (old_password: string, new_password: string) =>
    api.put<null>('/auth/password', { old_password, new_password }),
};

export const metaApi = {
  dicts: () => api.get<MetaDicts>('/meta/dicts'),
};

export const dashboardApi = {
  summary: () => api.get<DashboardSummary>('/dashboard/summary'),
  trend: (params: { variety_id?: number; region_id?: number; days?: number }) =>
    api.get<TrendData>('/dashboard/trend', params),
  alerts: (limit = 5) => api.get<AlertRow[]>('/dashboard/alerts/latest', { limit }),
  forecastBrief: (limit = 5) => api.get<unknown[]>('/dashboard/forecast-brief', { limit }),
};

export const priceApi = {
  series: (params: {
    variety_id?: number;
    region_id?: number;
    granularity?: 'day' | 'week' | 'month';
    days?: number;
  }) => api.get<TrendData>('/prices/series', params),
  list: (params: Record<string, unknown>) => api.get<PageData<PriceRow>>('/prices', params),
  stats: (params: Record<string, unknown>) => api.get<PriceStats>('/prices/stats', params),
  seasonality: (params: Record<string, unknown>) =>
    api.get<{ months: string[]; indices: number[] }>('/prices/seasonality', params),
};

export const forecastApi = {
  run: (body: { variety_id: number; region_id: number; horizon: number; granularity?: string }) =>
    api.post<ForecastResult>('/forecast/run', { granularity: 'day', ...body }),
  results: (params: { variety_id?: number; region_id?: number; limit?: number }) =>
    api.get<ForecastResult[]>('/forecast/results', params),
};

export const alertApi = {
  list: (params: Record<string, unknown>) => api.get<PageData<AlertRow>>('/alerts', params),
  detail: (id: number) => api.get<AlertRow>(`/alerts/${id}`),
  statistics: () => api.get<AlertStatistics>('/alerts/statistics'),
  ack: (id: number, note: string) => api.post<AlertRow>(`/alerts/${id}/ack`, { note }),
  close: (id: number, note: string, result: string) =>
    api.post<AlertRow>(`/alerts/${id}/close`, { note, result }),
};

export const notificationApi = {
  list: (params: { page?: number; page_size?: number } = {}) =>
    api.get<PageData<NotificationRow>>('/notifications', params),
  summary: () => api.get<NotificationSummary>('/notifications/summary'),
};
