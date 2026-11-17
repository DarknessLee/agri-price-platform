import { defineStore } from 'pinia';
import { ref } from 'vue';

import {
  clearSession,
  getStoredPermissions,
  getStoredUser,
  getToken,
  setStoredPermissions,
  setStoredUser,
  setToken,
} from '@/api/client';
import { authApi } from '@/api';
import type { UserBrief } from '@/types';

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getToken());
  const user = ref<UserBrief | null>(getStoredUser<UserBrief>());
  const permissions = ref<string[]>(getStoredPermissions());

  const isLoggedIn = () => Boolean(token.value);
  const isAdmin = () => user.value?.role_key === 'admin';

  function hasPerm(perm: string | string[]): boolean {
    if (!user.value) return false;
    if (user.value.role_key === 'admin') return true;
    const list = Array.isArray(perm) ? perm : [perm];
    return list.some((item) => permissions.value.includes(item));
  }

  async function login(username: string, password: string): Promise<void> {
    const result = await authApi.login(username, password);
    token.value = result.token;
    user.value = result.user;
    permissions.value = result.permissions || [];
    setToken(result.token);
    setStoredUser(result.user);
    setStoredPermissions(permissions.value);
  }

  async function fetchMe(): Promise<void> {
    const result = await authApi.me();
    user.value = result.user;
    permissions.value = result.permissions || [];
    setStoredUser(result.user);
    setStoredPermissions(permissions.value);
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout();
    } catch {
      // 忽略注销接口异常，本地状态仍需清理
    }
    reset();
  }

  function reset(): void {
    token.value = '';
    user.value = null;
    permissions.value = [];
    clearSession();
  }

  return {
    token,
    user,
    permissions,
    isLoggedIn,
    isAdmin,
    hasPerm,
    login,
    fetchMe,
    logout,
    reset,
  };
});
