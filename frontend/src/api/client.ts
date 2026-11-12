import axios, { type AxiosRequestConfig, type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'

export interface ApiEnvelope<T = unknown> {
  code: string
  message: string
  data: T
}

export interface Paged<T> {
  list: T[]
  total: number
  page: number
  page_size: number
}

const TOKEN_KEY = 'ap_token'
const USER_KEY = 'ap_user'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export function getStoredUser<T = unknown>(): T | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

export function setStoredUser(user: unknown) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
  else localStorage.removeItem(USER_KEY)
}

export class ApiError extends Error {
  code: string
  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    const payload = error?.response?.data
    if (status === 401) {
      setToken('')
      setStoredUser(null)
      if (!location.pathname.startsWith('/login')) {
        ElMessage.warning(payload?.message || '登录已失效，请重新登录')
        location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await http.request<ApiEnvelope<T>>(config)
  const body = response.data
  if (!body || typeof body !== 'object' || !('code' in body)) {
    return body as unknown as T
  }
  if (String(body.code) !== '0') {
    if (String(body.code) === 'E4010') {
      setToken('')
      setStoredUser(null)
      if (!location.pathname.startsWith('/login')) location.href = '/login'
    }
    throw new ApiError(String(body.code), body.message || '请求失败')
  }
  return body.data as T
}

export const api = {
  get<T>(url: string, params?: Record<string, unknown>, config?: AxiosRequestConfig) {
    return request<T>({ ...config, url, method: 'get', params })
  },
  post<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
    return request<T>({ ...config, url, method: 'post', data })
  },
  put<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
    return request<T>({ ...config, url, method: 'put', data })
  },
  delete<T>(url: string, params?: Record<string, unknown>, config?: AxiosRequestConfig) {
    return request<T>({ ...config, url, method: 'delete', params })
  },
  async download(url: string, params?: Record<string, unknown>, filename?: string) {
    const response = await http.get(url, { params, responseType: 'blob' })
    const blob = response.data as Blob
    const link = document.createElement('a')
    const objectUrl = URL.createObjectURL(blob)
    link.href = objectUrl
    link.download = filename || 'download'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(objectUrl)
  },
  async upload<T>(url: string, form: FormData) {
    return request<T>({
      url,
      method: 'post',
      data: form,
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
}

export default api
