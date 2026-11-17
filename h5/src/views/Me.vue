<template>
  <div class="h5-page me-page">
    <div class="h5-hero me-hero">
      <div class="me-profile">
        <div class="me-avatar">{{ avatarText }}</div>
        <div class="me-profile-text">
          <h1>{{ displayName }}</h1>
          <p>{{ accountLine }}</p>
          <p v-if="user?.org" class="me-org">{{ user.org }}</p>
        </div>
      </div>
    </div>

    <div class="h5-card me-overview">
      <div class="h5-kpi-grid">
        <div class="h5-kpi">
          <div class="h5-kpi-label">权限点</div>
          <div class="h5-kpi-value">{{ permissions.length }}<small>项</small></div>
          <div class="h5-kpi-hint">{{ roleName }}</div>
        </div>
        <div class="h5-kpi">
          <div class="h5-kpi-label">未读通知</div>
          <div class="h5-kpi-value">{{ unreadCount }}<small>条</small></div>
          <div class="h5-kpi-hint">通知详情在电脑端查看</div>
        </div>
      </div>
      <p class="me-note">菜单与操作权限由管理员分配，如需调整请联系系统管理员。</p>
    </div>

    <CellGroup inset class="me-cells">
      <Cell title="修改密码" icon="lock" is-link @click="openPassword" />
      <Cell title="查看通知" icon="bell" :value="notificationText" is-link @click="onViewNotifications" />
      <Cell title="关于平台" icon="info-o" is-link @click="aboutVisible = true" />
      <Cell title="退出登录" icon="sign" is-link @click="onLogout" />
    </CellGroup>

    <p class="me-footer">移动端仅支持查询与预警处置，管理功能请在电脑端使用</p>

    <Dialog
      v-model:show="passwordVisible"
      title="修改密码"
      show-cancel-button
      confirm-button-text="确认修改"
      :before-close="onPasswordClose"
    >
      <div class="me-form">
        <Field
          v-model="pwdOld"
          type="password"
          placeholder="请输入原密码"
          autocomplete="current-password"
          clearable
        />
        <Field
          v-model="pwdNew"
          type="password"
          placeholder="请输入新密码（至少 8 位字符）"
          autocomplete="new-password"
          clearable
        />
        <Field
          v-model="pwdConfirm"
          type="password"
          placeholder="请再次输入新密码"
          autocomplete="new-password"
          clearable
        />
      </div>
    </Dialog>

    <Popup v-model:show="aboutVisible" position="bottom" round closeable class="me-about-popup">
      <div class="me-about">
        <div class="me-about-head">关于平台</div>
        <div class="me-about-row">
          <span class="me-about-label">平台名称</span>
          <span class="me-about-value">农产品价格监测与预测平台</span>
        </div>
        <div class="me-about-row">
          <span class="me-about-label">移动端版本</span>
          <span class="me-about-value">V1.0</span>
        </div>
        <div class="me-about-row">
          <span class="me-about-label">接口地址</span>
          <span class="me-about-value mono">/api</span>
        </div>
        <div class="me-about-row me-about-row-top">
          <span class="me-about-label">移动端页面</span>
          <span class="me-about-value me-about-tags">
            <span v-for="page in mobilePages" :key="page" class="me-about-tag">{{ page }}</span>
          </span>
        </div>
        <p class="me-about-desc">
          移动端提供价格查询、预测查看与预警处置等常用能力，数据来源于平台统一接口；报表生成、模型训练等管理功能请在电脑端使用。
        </p>
        <Button type="primary" block round @click="aboutVisible = false">知道了</Button>
      </div>
    </Popup>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  Button,
  Cell,
  CellGroup,
  Dialog,
  Field,
  Popup,
  showConfirmDialog,
  showToast,
} from 'vant';

import { authApi, notificationApi } from '@/api';
import { useAuthStore } from '@/stores/auth';

const router = useRouter();
const auth = useAuthStore();

const user = computed(() => auth.user);
const permissions = computed(() => auth.permissions || []);

const displayName = computed(() => user.value?.display_name || user.value?.username || '用户');
const accountLine = computed(() => {
  const name = user.value?.username || '-';
  return `账号：${name}`;
});
const roleName = computed(() => user.value?.role_name || user.value?.role_key || '未分配角色');
const avatarText = computed(() => (user.value?.display_name || user.value?.username || '用').trim().charAt(0).toUpperCase());

const unreadCount = ref(0);
const notificationText = computed(() => (unreadCount.value > 0 ? `${unreadCount.value} 条未读` : '暂无未读'));

const passwordVisible = ref(false);
const pwdOld = ref('');
const pwdNew = ref('');
const pwdConfirm = ref('');
const submitting = ref(false);

const aboutVisible = ref(false);
const mobilePages = ['首页概览', '价格行情', '价格预测', '预警中心', '个人中心'];

async function loadNotification(): Promise<void> {
  try {
    const summary = await notificationApi.summary();
    unreadCount.value = Number(summary?.unread || 0);
  } catch {
    showToast('数据服务暂不可用');
  }
}

function openPassword(): void {
  pwdOld.value = '';
  pwdNew.value = '';
  pwdConfirm.value = '';
  passwordVisible.value = true;
}

async function onPasswordClose(action: string): Promise<boolean> {
  if (action !== 'confirm') return true;
  if (submitting.value) return false;
  if (!pwdOld.value) {
    showToast('请输入原密码');
    return false;
  }
  if (pwdNew.value.length < 8) {
    showToast('新密码至少 8 位字符');
    return false;
  }
  if (pwdNew.value !== pwdConfirm.value) {
    showToast('两次输入的新密码不一致');
    return false;
  }
  submitting.value = true;
  try {
    await authApi.changePassword(pwdOld.value, pwdNew.value);
    showToast('密码修改成功，请重新登录');
    await auth.logout();
    await router.replace('/login');
    return true;
  } catch {
    showToast('数据服务暂不可用');
    return false;
  } finally {
    submitting.value = false;
  }
}

function onViewNotifications(): void {
  if (unreadCount.value > 0) {
    showToast(`有 ${unreadCount.value} 条未读通知，请在电脑端查看`);
    return;
  }
  showToast('暂无未读通知，通知详情请在电脑端查看');
}

async function onLogout(): Promise<void> {
  try {
    await showConfirmDialog({
      title: '退出登录',
      message: '确定要退出当前账号吗？',
    });
  } catch {
    return;
  }
  await auth.logout();
  await router.replace('/login');
}

onMounted(() => {
  void loadNotification();
});
</script>

<style scoped>
.me-hero {
  padding-bottom: 22px;
}

.me-profile {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.me-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.9);
  color: var(--ap-primary);
  font-size: 22px;
  font-weight: 600;
}

.me-profile-text {
  min-width: 0;
}

.me-profile-text h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #fff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.me-profile-text p {
  margin: 3px 0 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.82);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.me-overview {
  margin-top: 12px;
}

.me-note {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ap-muted);
}

.me-cells {
  margin-top: 12px;
}

.me-footer {
  margin: 16px 0 4px;
  padding: 0 8px;
  font-size: 11px;
  line-height: 1.6;
  color: var(--ap-muted);
  text-align: center;
}

.me-form {
  padding: 4px 0;
  overflow: hidden;
}

.me-form :deep(.van-field) {
  border-radius: 8px;
  background: var(--ap-bg);
  margin-bottom: 10px;
}

.me-form :deep(.van-field:last-child) {
  margin-bottom: 0;
}

.me-about-popup {
  max-height: 82vh;
}

.me-about {
  padding: 18px 16px calc(18px + env(safe-area-inset-bottom));
  overflow-x: hidden;
}

.me-about-head {
  margin-bottom: 12px;
  font-size: 16px;
  font-weight: 600;
  color: var(--ap-text);
}

.me-about-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--ap-border);
  font-size: 13px;
}

.me-about-label {
  flex: 0 0 76px;
  color: var(--ap-muted);
}

.me-about-value {
  flex: 1;
  min-width: 0;
  color: var(--ap-text);
  text-align: right;
  word-break: break-all;
}

.me-about-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.me-about-tag {
  padding: 2px 8px;
  border-radius: 10px;
  background: #eef3fd;
  color: var(--ap-primary);
  font-size: 12px;
  line-height: 18px;
}

.me-about-desc {
  margin: 12px 0 16px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ap-muted);
  word-break: break-all;
}
</style>
