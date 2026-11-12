import api from '@/api/client'

export interface NotificationItem {
  id: number
  title: string
  content?: string
  category?: string
  level?: string
  link?: string
  is_read: boolean
  created_at?: string
}

export interface NotificationCategoryCount {
  category: string
  count: number
}

export interface NotificationSummary {
  unread: number
  by_category?: NotificationCategoryCount[]
}

export interface NotificationPage {
  list: NotificationItem[]
  total: number
  unread?: number
  page: number
  page_size: number
}

export interface NotificationQuery {
  unread_only?: boolean
  category?: string
  page?: number
  page_size?: number
}

export function fetchNotifications(params: NotificationQuery = {}) {
  return api.get<NotificationPage>('/notifications', { page: 1, page_size: 20, ...params })
}

export function fetchNotificationSummary() {
  return api.get<NotificationSummary>('/notifications/summary')
}

export function markNotificationRead(id: number) {
  return api.post<{ id: number; is_read: boolean }>(`/notifications/${id}/read`)
}

export function markAllNotificationsRead() {
  return api.post<{ updated: number }>('/notifications/read-all')
}
