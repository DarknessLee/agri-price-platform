<template>
  <div class="layout">
    <aside class="sidebar" :class="{ 'is-collapsed': collapsed }">
      <div class="brand">
        <div class="brand-logo">农</div>
        <div v-show="!collapsed" class="brand-text">
          <strong>农产品价格</strong>
          <span>监测预测分析平台</span>
        </div>
      </div>

      <el-scrollbar class="menu-scroll">
        <el-menu
          :default-active="activePath"
          :collapse="collapsed"
          :collapse-transition="false"
          router
          background-color="transparent"
          text-color="#c7d3e6"
          active-text-color="#ffffff"
          class="side-menu"
          unique-opened
        >
          <template v-for="item in menus" :key="item.key">
            <el-sub-menu v-if="item.children && item.children.length" :index="item.key">
              <template #title>
                <el-icon><component :is="item.icon || 'Menu'" /></el-icon>
                <span>{{ item.title }}</span>
              </template>
              <el-menu-item v-for="child in item.children" :key="child.key" :index="child.path">
                <el-icon><component :is="child.icon || 'Document'" /></el-icon>
                <template #title>{{ child.title }}</template>
              </el-menu-item>
            </el-sub-menu>
            <el-menu-item v-else :index="item.path">
              <el-icon><component :is="item.icon || 'Document'" /></el-icon>
              <template #title>{{ item.title }}</template>
            </el-menu-item>
          </template>
        </el-menu>
      </el-scrollbar>

      <div v-show="!collapsed" class="sidebar-foot">
        <span>数据更新</span>
        <strong>{{ updateText }}</strong>
      </div>
    </aside>

    <section class="main">
      <header class="topbar">
        <el-icon class="collapse-btn" @click="collapsed = !collapsed">
          <Expand v-if="collapsed" />
          <Fold v-else />
        </el-icon>
        <div class="crumbs">
          <span class="crumb-group">{{ currentGroup }}</span>
          <span class="crumb-sep">/</span>
          <span class="crumb-title">{{ currentTitle }}</span>
        </div>
        <div class="grow" />
        <div class="top-date">
          <el-icon><Calendar /></el-icon>
          <span>{{ today }}</span>
        </div>
        <NotificationBell />
        <el-divider direction="vertical" />
        <el-dropdown trigger="click" @command="onUserCommand">
          <div class="user-chip">
            <div class="avatar">{{ (auth.displayName || 'A').slice(0, 1) }}</div>
            <div class="user-meta">
              <strong>{{ auth.displayName }}</strong>
              <span>{{ roleName }}</span>
            </div>
            <el-icon><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="password">
                <el-icon><Key /></el-icon>修改密码
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided>
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </header>

      <main class="content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </section>

    <el-dialog v-model="passwordVisible" title="修改密码" width="420px" append-to-body>
      <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-width="90px">
        <el-form-item label="原密码" prop="old_password">
          <el-input v-model="passwordForm.old_password" type="password" show-password autocomplete="off" />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="passwordForm.new_password" type="password" show-password autocomplete="off" />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm">
          <el-input v-model="passwordForm.confirm" type="password" show-password autocomplete="off" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordVisible = false">取消</el-button>
        <el-button type="primary" :loading="passwordSaving" @click="submitPassword">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import api from '@/api/client'
import NotificationBell from '@/components/NotificationBell.vue'
import { useAuthStore } from '@/stores/auth'
import { FALLBACK_MENUS } from '@/constants/menus'
import type { MenuNode } from '@/types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const collapsed = ref(false)
const menus = ref<MenuNode[]>(FALLBACK_MENUS)
const updateText = ref('每日 08:00')

const activePath = computed(() => route.path)
const currentTitle = computed(() => (route.meta.title as string) || '综合驾驶舱')
const currentGroup = computed(() => (route.meta.group as string) || '总览')
const roleName = computed(() => auth.user?.role_name || auth.roleKey)
const today = new Date().toLocaleDateString('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  weekday: 'short',
})

const passwordVisible = ref(false)
const passwordSaving = ref(false)
const passwordFormRef = ref<FormInstance>()
const passwordForm = reactive({ old_password: '', new_password: '', confirm: '' })
const passwordRules: FormRules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码长度不少于 8 位', trigger: 'blur' },
  ],
  confirm: [
    {
      validator: (_rule, value, callback) => {
        if (!value) callback(new Error('请再次输入新密码'))
        else if (value !== passwordForm.new_password) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

async function loadMenus() {
  try {
    const data = await api.get<MenuNode[]>('/meta/menus')
    if (Array.isArray(data) && data.length) menus.value = data
  } catch {
    menus.value = FALLBACK_MENUS
  }
}

async function onUserCommand(command: string) {
  if (command === 'password') {
    passwordForm.old_password = ''
    passwordForm.new_password = ''
    passwordForm.confirm = ''
    passwordVisible.value = true
  } else if (command === 'logout') {
    await auth.logout()
    ElMessage.success('已退出登录')
    router.push('/login')
  }
}

async function submitPassword() {
  if (!passwordFormRef.value) return
  const valid = await passwordFormRef.value.validate().catch(() => false)
  if (!valid) return
  passwordSaving.value = true
  try {
    await api.put('/auth/password', {
      old_password: passwordForm.old_password,
      new_password: passwordForm.new_password,
    })
    passwordVisible.value = false
    ElMessage.success('密码已更新，请重新登录')
    await auth.logout()
    router.push('/login')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '密码修改失败')
  } finally {
    passwordSaving.value = false
  }
}

onMounted(() => {
  loadMenus()
})
</script>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  display: flex;
  flex-direction: column;
  width: 232px;
  background: linear-gradient(180deg, #12233f 0%, #0d1a30 100%);
  transition: width 0.2s ease;
  flex-shrink: 0;
}

.sidebar.is-collapsed {
  width: 64px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 64px;
  padding: 0 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  overflow: hidden;
  white-space: nowrap;
}

.brand-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: linear-gradient(135deg, #2f7bff, #1f5fd6);
  color: #fff;
  font-size: 18px;
  font-weight: 700;
  flex-shrink: 0;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  color: #fff;
}

.brand-text strong {
  font-size: 15px;
  letter-spacing: 1px;
}

.brand-text span {
  font-size: 11px;
  color: #8fa4c4;
}

.menu-scroll {
  flex: 1;
  padding: 8px 0;
}

.side-menu {
  border-right: none;
}

.side-menu :deep(.el-menu-item),
.side-menu :deep(.el-sub-menu__title) {
  height: 44px;
  line-height: 44px;
  margin: 2px 10px;
  border-radius: 8px;
}

.side-menu :deep(.el-menu-item:hover),
.side-menu :deep(.el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, 0.06) !important;
}

.side-menu :deep(.el-menu-item.is-active) {
  background: var(--ap-primary) !important;
  box-shadow: 0 4px 12px rgba(31, 95, 214, 0.35);
}

.sidebar-foot {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 18px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 12px;
  color: #8fa4c4;
}

.sidebar-foot strong {
  color: #dce6f5;
  font-weight: 500;
}

.main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  height: 64px;
  padding: 0 22px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(20, 40, 80, 0.06);
  position: relative;
  z-index: 5;
}

.collapse-btn {
  font-size: 19px;
  color: #41546e;
  cursor: pointer;
}

.crumbs {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
}

.crumb-group {
  color: #7b8ba1;
}

.crumb-sep {
  color: #c0cad8;
}

.crumb-title {
  font-size: 16px;
  font-weight: 600;
  color: #1c2a3a;
}

.top-date {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #6b7c93;
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 10px 4px 4px;
  border-radius: 22px;
  cursor: pointer;
  transition: background 0.15s;
}

.user-chip:hover {
  background: #f2f5fb;
}

.avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, #2f7bff, #17479f);
  color: #fff;
  font-weight: 600;
}

.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.user-meta strong {
  font-size: 13px;
  color: #1c2a3a;
}

.user-meta span {
  font-size: 11px;
  color: #8b9aae;
}

.content {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px 26px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
