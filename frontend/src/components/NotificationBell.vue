<template>
  <div class="notification-bell">
    <el-popover
      v-model:visible="popoverVisible"
      placement="bottom-end"
      :width="364"
      trigger="click"
      popper-class="notify-popover"
    >
      <template #reference>
        <div class="bell-trigger" :class="{ 'has-unread': unread > 0 }" title="通知中心">
          <el-badge :value="unread" :max="99" :hidden="unread <= 0" class="bell-badge">
            <el-icon :size="18"><Bell /></el-icon>
          </el-badge>
        </div>
      </template>

      <div class="notify-panel">
        <div class="notify-head">
          <div class="notify-head-left">
            <span class="notify-head-title">通知中心</span>
            <span v-if="unread > 0" class="notify-unread-tip">{{ unread }} 条未读</span>
          </div>
          <el-button link type="primary" size="small" :disabled="unread <= 0" @click="handleReadAll">
            全部已读
          </el-button>
        </div>

        <div v-if="loading" class="notify-state">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>加载中…</span>
        </div>
        <div v-else-if="!items.length" class="notify-state">
          <el-icon><Bell /></el-icon>
          <span>暂无通知</span>
        </div>
        <ul v-else class="notify-list">
          <li
            v-for="item in items"
            :key="item.id"
            class="notify-item"
            :class="{ 'is-unread': !item.is_read }"
            @click="handleItem(item)"
          >
            <span class="notify-dot" :class="{ show: !item.is_read }" />
            <div class="notify-body">
              <div class="notify-line">
                <el-tag v-if="item.category" size="small" effect="light" :type="categoryTagType(item.category)">
                  {{ item.category }}
                </el-tag>
                <span class="notify-title">{{ item.title }}</span>
              </div>
              <div class="notify-sub">
                <span class="notify-content">{{ item.content || '点击查看详情' }}</span>
                <span class="notify-time">{{ relativeTime(item.created_at) }}</span>
              </div>
            </div>
          </li>
        </ul>

        <div class="notify-foot">
          <el-button link size="small" @click="openAll">
            查看全部
            <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
      </div>
    </el-popover>

    <el-dialog v-model="dialogVisible" title="通知中心" width="560px" append-to-body>
      <div v-if="dialogLoading" class="notify-state">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>加载中…</span>
      </div>
      <div v-else-if="!fullItems.length" class="notify-state">
        <el-icon><Bell /></el-icon>
        <span>暂无通知</span>
      </div>
      <ul v-else class="notify-list is-full">
        <li
          v-for="item in fullItems"
          :key="item.id"
          class="notify-item"
          :class="{ 'is-unread': !item.is_read }"
          @click="handleItem(item)"
        >
          <span class="notify-dot" :class="{ show: !item.is_read }" />
          <div class="notify-body">
            <div class="notify-line">
              <el-tag v-if="item.category" size="small" effect="light" :type="categoryTagType(item.category)">
                {{ item.category }}
              </el-tag>
              <span class="notify-title">{{ item.title }}</span>
            </div>
            <div class="notify-sub">
              <span class="notify-content">{{ item.content || '点击查看详情' }}</span>
              <span class="notify-time">{{ relativeTime(item.created_at) }}</span>
            </div>
          </div>
        </li>
      </ul>
      <template #footer>
        <el-button size="small" @click="dialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  fetchNotifications,
  fetchNotificationSummary,
  markNotificationRead,
  markAllNotificationsRead,
  type NotificationItem,
} from '@/api/notifications'
import { fmtDate } from '@/utils/format'

type TagType = '' | 'primary' | 'success' | 'warning' | 'danger' | 'info'

const router = useRouter()

const unread = ref(0)
const items = ref<NotificationItem[]>([])
const fullItems = ref<NotificationItem[]>([])
const loading = ref(false)
const dialogLoading = ref(false)
const popoverVisible = ref(false)
const dialogVisible = ref(false)

let pollTimer: number | undefined

async function loadPreview() {
  try {
    const data = await fetchNotifications({ page: 1, page_size: 8 })
    items.value = Array.isArray(data?.list) ? data.list : []
    if (typeof data?.unread === 'number') unread.value = data.unread
  } catch {
    /* 通知服务未就绪时静默降级 */
  }
}

async function loadSummary() {
  try {
    const data = await fetchNotificationSummary()
    if (typeof data?.unread === 'number') unread.value = data.unread
  } catch {
    /* 汇总接口未就绪时静默降级 */
  }
}

async function refresh() {
  loading.value = true
  await Promise.allSettled([loadPreview(), loadSummary()])
  loading.value = false
}

async function openFull() {
  dialogVisible.value = true
  dialogLoading.value = true
  try {
    const data = await fetchNotifications({ page: 1, page_size: 20 })
    fullItems.value = Array.isArray(data?.list) ? data.list : []
    if (typeof data?.unread === 'number') unread.value = data.unread
  } catch {
    fullItems.value = []
  } finally {
    dialogLoading.value = false
  }
}

function openAll() {
  popoverVisible.value = false
  void openFull()
}

async function handleItem(item: NotificationItem) {
  if (!item.is_read) {
    item.is_read = true
    unread.value = Math.max(0, unread.value - 1)
    try {
      await markNotificationRead(item.id)
    } catch {
      /* 已读接口未就绪时静默降级 */
    }
  }
  const target = item.link || ''
  if (target) {
    popoverVisible.value = false
    dialogVisible.value = false
    router.push(target)
  }
}

async function handleReadAll() {
  if (unread.value <= 0 && items.value.every((item) => item.is_read)) return
  items.value.forEach((item) => {
    item.is_read = true
  })
  fullItems.value.forEach((item) => {
    item.is_read = true
  })
  unread.value = 0
  try {
    await markAllNotificationsRead()
  } catch {
    /* 全部已读接口未就绪时静默降级 */
  }
}

function categoryTagType(category?: string): TagType {
  switch (category) {
    case '预警':
      return 'danger'
    case '数据':
      return 'primary'
    case '报告':
      return 'success'
    case '模型':
      return 'warning'
    case '任务':
      return 'info'
    default:
      return 'info'
  }
}

function relativeTime(value?: string): string {
  if (!value) return ''
  const time = new Date(String(value).replace(' ', 'T')).getTime()
  if (!Number.isFinite(time)) return fmtDate(value)
  const diff = Date.now() - time
  if (diff < 0) return fmtDate(value)
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return fmtDate(value)
}

watch(popoverVisible, (visible) => {
  if (visible) void refresh()
})

onMounted(() => {
  void refresh()
  pollTimer = window.setInterval(() => {
    void refresh()
  }, 30000)
})

onUnmounted(() => {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
})
</script>

<style scoped>
.notification-bell {
  display: inline-flex;
  align-items: center;
}

.bell-trigger {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  color: #4d5f76;
  cursor: pointer;
  transition: background-color 0.2s, color 0.2s;
}

.bell-trigger:hover,
.bell-trigger.has-unread {
  background: #eef4ff;
  color: #1f5fd6;
}

.bell-badge {
  display: flex;
  align-items: center;
}

.bell-badge :deep(.el-badge__content) {
  font-size: 10px;
  height: 16px;
  line-height: 16px;
  padding: 0 5px;
  border: 1px solid #fff;
}

.notify-panel {
  margin: -4px -2px;
}

.notify-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 2px 9px;
  border-bottom: 1px solid #eef1f5;
}

.notify-head-left {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.notify-head-title {
  font-size: 14px;
  font-weight: 600;
  color: #1d2b3f;
}

.notify-unread-tip {
  font-size: 11px;
  color: #8a97a8;
}

.notify-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 28px 0;
  font-size: 12px;
  color: #98a5b5;
}

.notify-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 336px;
  overflow-y: auto;
}

.notify-list.is-full {
  max-height: 440px;
}

.notify-item {
  display: flex;
  gap: 8px;
  padding: 10px 6px;
  border-radius: 6px;
  border-bottom: 1px solid #f4f6f9;
  cursor: pointer;
  transition: background-color 0.2s;
}

.notify-item:last-child {
  border-bottom: none;
}

.notify-item:hover {
  background: #f5f9ff;
}

.notify-item.is-unread {
  background: #f8fbff;
}

.notify-dot {
  width: 6px;
  height: 6px;
  margin-top: 8px;
  border-radius: 50%;
  background: transparent;
  flex-shrink: 0;
}

.notify-dot.show {
  background: #d64545;
}

.notify-body {
  flex: 1;
  min-width: 0;
}

.notify-line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.notify-line :deep(.el-tag) {
  flex-shrink: 0;
  height: 18px;
  padding: 0 5px;
  font-size: 10px;
  border-radius: 3px;
}

.notify-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2d3d;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.notify-sub {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 4px;
}

.notify-content {
  font-size: 12px;
  color: #7b8a9e;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.notify-time {
  font-size: 11px;
  color: #a2adbb;
  white-space: nowrap;
  flex-shrink: 0;
}

.notify-foot {
  padding-top: 8px;
  border-top: 1px solid #eef1f5;
  text-align: center;
}
</style>
