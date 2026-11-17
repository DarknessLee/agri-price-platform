<template>
  <div class="login-page">
    <section class="brand">
      <div class="brand-badge">
        <VanIcon name="chart-trending-o" size="26" />
      </div>
      <h1 class="brand-title">农产品价格监测预测分析平台</h1>
      <p class="brand-sub">移动端 · 行情查询与预警</p>
      <div class="brand-tags">
        <span>价格行情</span>
        <span>趋势预测</span>
        <span>预警处置</span>
      </div>
    </section>

    <section class="login-card">
      <div class="card-head">
        <span class="card-title">账号登录</span>
        <span class="card-hint">统一身份认证</span>
      </div>

      <form class="login-form" @submit.prevent="onSubmit">
        <VanCellGroup :border="false" class="form-group">
          <VanField
            v-model="username"
            name="username"
            label="用户名"
            placeholder="请输入用户名"
            left-icon="user-o"
            autocomplete="username"
            clearable
            :border="true"
          />
          <VanField
            v-model="password"
            name="password"
            label="密码"
            placeholder="请输入密码"
            left-icon="lock"
            autocomplete="current-password"
            :border="false"
            :type="showPassword ? 'text' : 'password'"
            :right-icon="showPassword ? 'eye-o' : 'closed-eye'"
            @click-right-icon="showPassword = !showPassword"
          />
        </VanCellGroup>

        <VanButton
          class="login-btn"
          block
          round
          type="primary"
          native-type="submit"
          :loading="loading"
          loading-text="登录中…"
          :disabled="loading"
        >
          登录
        </VanButton>
      </form>

      <p class="login-note">登录后可在移动端查询行情、预测与预警，并完成预警处置。</p>
    </section>

    <section class="accounts">
      <div class="accounts-head">
        <span class="accounts-title">验收账号</span>
        <span class="accounts-hint">点击任一账号快速填入</span>
      </div>
      <button
        v-for="item in ACCOUNTS"
        :key="item.username"
        type="button"
        class="account-row"
        @click="fillAccount(item)"
      >
        <span class="account-main">
          <span class="account-name">{{ item.username }}</span>
          <span class="account-password">{{ item.password }}</span>
        </span>
        <span class="account-role">{{ item.role }}</span>
        <VanIcon name="arrow" size="12" class="account-arrow" />
      </button>
    </section>

    <footer class="login-footer">
      <p>移动端仅提供行情、预测、预警查询与处置，管理类操作请在电脑端完成。</p>
      <p class="footer-version">农产品价格监测预测分析平台 · V1.0</p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  Button as VanButton,
  CellGroup as VanCellGroup,
  Field as VanField,
  Icon as VanIcon,
  showFailToast,
  showSuccessToast,
  showToast,
} from 'vant';

import { useAuthStore } from '@/stores/auth';

interface AccountItem {
  username: string;
  password: string;
  role: string;
}

const ACCOUNTS: AccountItem[] = [
  { username: 'admin', password: 'Admin@2026', role: '系统管理员' },
  { username: 'analyst01', password: 'Analyst@2026', role: '分析师' },
  { username: 'operator01', password: 'Operator@2026', role: '业务操作员' },
  { username: 'viewer01', password: 'Viewer@2026', role: '只读用户' },
];

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const username = ref('');
const password = ref('');
const showPassword = ref(false);
const loading = ref(false);

function fillAccount(item: AccountItem): void {
  username.value = item.username;
  password.value = item.password;
  showPassword.value = false;
  showToast(`已填入${item.role}账号`);
}

async function onSubmit(): Promise<void> {
  if (loading.value) return;
  const name = username.value.trim();
  if (!name) {
    showToast('请输入用户名');
    return;
  }
  if (!password.value) {
    showToast('请输入密码');
    return;
  }

  loading.value = true;
  try {
    await auth.login(name, password.value);
    showSuccessToast('登录成功');
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '';
    await router.replace(redirect || '/');
  } catch (error) {
    const message = error instanceof Error && error.message ? error.message : '登录失败，请稍后重试';
    showFailToast(message);
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
  overflow-x: hidden;
  background: #eef3fb;
}

.brand {
  position: relative;
  padding: calc(56px + env(safe-area-inset-top)) 22px 64px;
  overflow: hidden;
  color: #fff;
  background: linear-gradient(150deg, #0b1c33 0%, #12386c 52%, #1f5fd6 100%);
}

.brand::before,
.brand::after {
  content: '';
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
}

.brand::before {
  top: -70px;
  right: -50px;
  width: 210px;
  height: 210px;
  background: radial-gradient(circle, rgba(95, 158, 255, 0.38) 0%, rgba(95, 158, 255, 0) 70%);
}

.brand::after {
  bottom: -90px;
  left: -60px;
  width: 220px;
  height: 220px;
  background: radial-gradient(circle, rgba(47, 158, 143, 0.28) 0%, rgba(47, 158, 143, 0) 70%);
}

.brand-badge {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  margin-bottom: 16px;
  border: 1px solid rgba(255, 255, 255, 0.28);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(2px);
}

.brand-title {
  position: relative;
  margin: 0;
  font-size: 21px;
  font-weight: 600;
  line-height: 1.4;
  letter-spacing: 0.5px;
}

.brand-sub {
  position: relative;
  margin: 8px 0 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.78);
}

.brand-tags {
  position: relative;
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.brand-tags span {
  padding: 3px 9px;
  border: 1px solid rgba(255, 255, 255, 0.22);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.1);
  font-size: 11px;
  color: rgba(255, 255, 255, 0.9);
}

.login-card {
  position: relative;
  margin: -40px 16px 0;
  padding: 18px 16px 16px;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 10px 30px rgba(11, 28, 51, 0.12);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--ap-text);
}

.card-hint {
  font-size: 11px;
  color: var(--ap-muted);
}

.form-group {
  overflow: hidden;
  margin-bottom: 16px;
  border-radius: 12px;
  background: #f7f9fd;
}

.form-group :deep(.van-cell) {
  padding: 11px 12px;
  background: transparent;
}

.form-group :deep(.van-field__label) {
  width: 54px;
  color: var(--ap-text-2);
  font-size: 13px;
}

.form-group :deep(.van-field__control) {
  font-size: 14px;
}

.login-btn {
  height: 44px;
  font-size: 15px;
  letter-spacing: 4px;
}

.login-note {
  margin: 10px 2px 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--ap-muted);
  text-align: center;
}

.accounts {
  margin: 16px 16px 0;
  padding: 12px 14px 4px;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 1px 3px rgba(18, 35, 63, 0.05);
}

.accounts-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding-bottom: 6px;
}

.accounts-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ap-text);
}

.accounts-title::before {
  content: '';
  display: inline-block;
  width: 3px;
  height: 12px;
  margin-right: 6px;
  border-radius: 2px;
  background: var(--ap-primary);
  vertical-align: -2px;
}

.accounts-hint {
  font-size: 11px;
  color: var(--ap-muted);
}

.account-row {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 9px 0;
  border: none;
  border-bottom: 1px solid var(--ap-border);
  background: transparent;
  text-align: left;
}

.account-row:last-child {
  border-bottom: none;
}

.account-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.account-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--ap-text);
}

.account-password {
  font-size: 11px;
  color: var(--ap-muted);
  font-variant-numeric: tabular-nums;
}

.account-role {
  margin-right: 4px;
  font-size: 11px;
  color: var(--ap-primary);
}

.account-arrow {
  color: var(--ap-muted);
}

.login-footer {
  padding: 18px 24px calc(22px + env(safe-area-inset-bottom));
  text-align: center;
}

.login-footer p {
  margin: 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--ap-muted);
}

.login-footer .footer-version {
  margin-top: 8px;
  color: #a8b1c2;
}
</style>
