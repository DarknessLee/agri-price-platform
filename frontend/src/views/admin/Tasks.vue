<template>
  <div class="page">
    <PageHeader title="任务调度" subtitle="查看定时任务执行计划，支持手动触发与启停控制">
      <template #actions>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <div class="page-card">
      <div class="toolbar">
        <el-tag type="success" effect="plain">启用 {{ enabledCount }} 个</el-tag>
        <el-tag type="warning" effect="plain">暂停 {{ pausedCount }} 个</el-tag>
        <span class="muted grow" style="text-align: right">
          共 {{ tasks.length }} 个调度任务，执行结果将记录到操作审计
        </span>
      </div>

      <el-table v-loading="loading" :data="tasks" stripe border>
        <el-table-column label="任务名称" min-width="190">
          <template #default="{ row }">
            <div class="task-name">{{ row.name }}</div>
            <div class="task-key mono">{{ row.key }}</div>
          </template>
        </el-table-column>
        <el-table-column label="执行计划（cron）" width="150">
          <template #default="{ row }">
            <span class="mono">{{ row.cron }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === '启用' ? 'success' : 'warning'" effect="light">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="上次执行" width="168">
          <template #default="{ row }">
            <span class="mono muted">{{ fmtDateTime(row.last_run_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_result" label="上次执行结果" min-width="250" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ muted: !row.last_result }">{{ row.last_result || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="下次执行" width="168">
          <template #default="{ row }">
            <span class="mono muted">{{ fmtDateTime(row.next_run_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="任务说明" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="178" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :loading="runningId === row.id"
              :disabled="runningId !== null && runningId !== row.id"
              @click="runNow(row)"
            >
              立即执行
            </el-button>
            <el-button link :type="row.status === '启用' ? 'warning' : 'success'" @click="toggle(row)">
              {{ row.status === '启用' ? '暂停' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无调度任务" />
        </template>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import api, { ApiError } from '@/api/client'
import { fmtDateTime } from '@/utils/format'

interface TaskRow {
  id: number
  key: string
  name: string
  cron: string
  status: string
  last_run_at?: string | null
  last_result?: string | null
  next_run_at?: string | null
  description?: string
}

const tasks = ref<TaskRow[]>([])
const loading = ref(false)
const runningId = ref<number | null>(null)

const enabledCount = computed(() => tasks.value.filter((item) => item.status === '启用').length)
const pausedCount = computed(() => tasks.value.filter((item) => item.status !== '启用').length)

function errorOf(err: unknown): string {
  if (err instanceof ApiError) return err.message
  const payload = (err as { response?: { data?: { message?: string } } })?.response?.data
  return payload?.message || ''
}

function warn(err: unknown) {
  const message = errorOf(err)
  ElMessage.warning(message && message !== 'Network Error' ? message : '数据服务暂不可用')
}

function nowText(): string {
  const d = new Date()
  const pad = (num: number) => String(num).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function load() {
  loading.value = true
  try {
    const list = await api.get<TaskRow[]>('/tasks')
    tasks.value = list || []
  } catch (err) {
    tasks.value = []
    warn(err)
  } finally {
    loading.value = false
  }
}

async function runNow(row: TaskRow) {
  runningId.value = row.id
  try {
    const res = await api.post<{ ok: boolean; result: string }>(`/tasks/${row.id}/run`)
    row.last_result = res.result
    row.last_run_at = nowText()
    ElMessage.success(res.result || '任务执行完成')
  } catch (err) {
    warn(err)
  } finally {
    runningId.value = null
  }
}

async function toggle(row: TaskRow) {
  try {
    const res = await api.post<{ ok: boolean; status: string }>(`/tasks/${row.id}/toggle`)
    row.status = res.status
    ElMessage.success(`任务「${row.name}」已${res.status === '启用' ? '启用' : '暂停'}`)
  } catch (err) {
    warn(err)
  }
}

onMounted(load)
</script>

<style scoped>
.task-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ap-text);
}

.task-key {
  font-size: 11px;
  color: #8b9aae;
  margin-top: 2px;
}

.page :deep(.el-table) {
  font-size: 13px;
}
</style>
