import axios from 'axios';

const TOKEN_KEY = 'ap_token';
const USER_KEY = 'ap_user';
const PERM_KEY = 'ap_perms';

export interface ApiEnvelope<T> {
  code: string | number;
  message: string;
  data: T;
  headers?: Record<string, string>;
}

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status = 0) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

http.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      setToken('');
      localStorage.removeItem(USER_KEY);
      localStorage.removeItem(PERM_KEY);
      if (!location.pathname.endsWith('/login')) {
        location.hash = '';
        location.replace('/m/login');
      }
    }
    return Promise.reject(error);
  },
);

async function unwrap<T>(promise: Promise<{ data: ApiEnvelope<T>; status: number }>): Promise<T> {
  const response = await promise;
  const body = response.data;
  if (body && typeof body === 'object' && 'code' in body) {
    if (String(body.code) !== '0') {
      throw new ApiError(String(body.code), body.message || '请求失败', response.status);
    }
    return body.data;
  }
  return body as unknown as T;
}

export const api = {
  get: <T>(url: string, params?: Record<string, unknown>) => unwrap<T>(http.get(url, { params })),
  post: <T>(url: string, data?: unknown) => unwrap<T>(http.post(url, data)),
  put: <T>(url: string, data?: unknown) => unwrap<T>(http.put(url, data)),
  delete: <T>(url: string) => unwrap<T>(http.delete(url)),
};

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setToken(token: string): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function getStoredUser<T>(): T | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function setStoredUser(user: unknown): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getStoredPermissions(): string[] {
  const raw = localStorage.getItem(PERM_KEY);
  if (!raw) return [];
  try {
    return JSON.parse(raw) as string[];
  } catch {
    return [];
  }
}

export function setStoredPermissions(perms: string[]): void {
  localStorage.setItem(PERM_KEY, JSON.stringify(perms));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(PERM_KEY);
}
