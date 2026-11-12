import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import api, { getStoredUser, getToken, setStoredUser, setToken } from '@/api/client'
import type { LoginResult, UserBrief } from '@/types'

const PERM_KEY = 'ap_perms'

function readPerms(): string[] {
  try {
    const raw = localStorage.getItem(PERM_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(getToken())
  const user = ref<UserBrief | null>(getStoredUser<UserBrief>())
  const permissions = ref<string[]>(readPerms())

  const isLoggedIn = computed(() => Boolean(token.value))
  const roleKey = computed(() => user.value?.role_key || '')
  const isAdmin = computed(() => roleKey.value === 'admin')
  const displayName = computed(() => user.value?.display_name || user.value?.username || '')

  function apply(payload: LoginResult) {
    token.value = payload.token
    user.value = payload.user
    permissions.value = payload.permissions || []
    setToken(payload.token)
    setStoredUser(payload.user)
    localStorage.setItem(PERM_KEY, JSON.stringify(permissions.value))
  }

  function hasPerm(perm?: string | string[]): boolean {
    if (!perm || (Array.isArray(perm) && perm.length === 0)) return true
    if (isAdmin.value) return true
    const needed = Array.isArray(perm) ? perm : [perm]
    return needed.some((p) => permissions.value.includes(p))
  }

  async function login(username: string, password: string) {
    const payload = await api.post<LoginResult>('/auth/login', { username, password })
    apply(payload)
    return payload
  }

  async function fetchMe() {
    const payload = await api.get<{ user: UserBrief; permissions: string[] }>('/auth/me')
    user.value = payload.user
    permissions.value = payload.permissions || []
    setStoredUser(payload.user)
    localStorage.setItem(PERM_KEY, JSON.stringify(permissions.value))
    return payload
  }

  function reset() {
    token.value = ''
    user.value = null
    permissions.value = []
    setToken('')
    setStoredUser(null)
    localStorage.removeItem(PERM_KEY)
  }

  async function logout() {
    try {
      await api.post('/auth/logout')
    } catch {
      /* 忽略退出接口异常，本地状态仍需清理 */
    }
    reset()
  }

  return {
    token,
    user,
    permissions,
    isLoggedIn,
    isAdmin,
    roleKey,
    displayName,
    hasPerm,
    login,
    fetchMe,
    logout,
    reset,
  }
})
