<template>
  <div class="page">
    <PageHeader title="任务调度" subtitle="查看定时任务执行计划，支持手动触发、启停控制与运行史追溯">
      <template #actions>
        <el-button :icon="Clock" @click="openGlobalRuns">全局运行史</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <div class="page-card">
      <div class="toolbar">
        <el-tag type="success" effect="plain">启用 {{ enabledCount }} 个</el-tag>
        <el-tag type="warning" effect="plain">暂停 {{ pausedCount }} 个</el-tag>
        <span class="muted grow" style="text-align: right">
          共 {{ tasks.length }} 个调度任务，执行结果将记录到运行史
        </span>
      </div>

      <el-table v-loading="loading" :data="tasks" stripe border>
        <el-table-column label="任务名称" min-width="190">
          <template #default="{ row }">
            <div class="task-name">{{ row.name }}</div>
            <div class="task-key mono">{{ row.key }}</div>
          </template>
        </el-table-column>
        <el-table-column label="执行计划" width="178">
          <template #default="{ row }">
            <div class="mono">{{ row.cron }}</div>
            <div class="task-cron-text">{{ row.cron_text || row.description || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="86" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === '启用' ? 'success' : 'warning'" effect="light">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="上次执行" width="162">
          <template #default="{ row }">
            <span class="mono muted">{{ fmtDateTime(row.last_run_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="下次执行" width="162">
          <template #default="{ row }">
            <span class="mono muted">{{ fmtDateTime(row.next_run_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="运行次数" width="94" align="center">
          <template #default="{ row }">
            <el-tag type="info" effect="plain">{{ row.runs ?? 0 }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_result" label="上次执行结果" min-width="230" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ muted: !row.last_result }">{{ row.last_result || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="任务说明" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="216" fixed="right">
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
            <el-button link type="primary" @click="openTaskRuns(row)">运行史</el-button>
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

    <el-drawer v-model="runDrawerVisible" :title="`运行史 · ${currentTask?.name || ''}`" size="780px" destroy-on-close>
      <div class="toolbar run-toolbar">
        <el-tag type="info" effect="plain">累计 {{ runTotal }} 次</el-tag>
        <el-tag v-if="currentTask" type="primary" effect="plain">
          {{ currentTask.cron_text || currentTask.cron }}
        </el-tag>
        <span class="grow" />
        <el-button size="small" :icon="Refresh" :loading="runLoading" @click="loadTaskRuns()">刷新</el-button>
      </div>
      <el-table v-loading="runLoading" :data="runs" stripe border size="small">
        <el-table-column label="开始时间" width="164">
          <template #default="{ row }">
            <span class="mono">{{ fmtDateTime(row.started_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="86" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === '成功' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发方式" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.trigger === '定时' ? 'info' : 'warning'" effect="plain" size="small">
              {{ row.trigger || '手动' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="96" align="right">
          <template #default="{ row }">
            <span class="mono">{{ row.duration_ms != null ? `${row.duration_ms} ms` : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="结果" min-width="260">
          <template #default="{ row }">
            <span :class="{ 'run-error': row.status === '失败' }">
              {{ row.status === '失败' ? row.error || row.result || '执行失败' : row.result || '—' }}
            </span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="runFailed ? '数据服务暂不可用' : '暂无运行记录'" />
        </template>
      </el-table>
      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="runPage"
          v-model:page-size="runPageSize"
          :total="runTotal"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @current-change="loadTaskRuns()"
          @size-change="onRunSizeChange"
        />
      </div>
    </el-drawer>

    <el-drawer v-model="globalVisible" title="全局运行史" size="880px" destroy-on-close>
      <div class="toolbar run-toolbar">
        <el-select v-model="globalStatus" placeholder="全部状态" clearable style="width: 130px" @change="onGlobalFilterChange">
          <el-option label="全部状态" value="" />
          <el-option label="成功" value="成功" />
          <el-option label="失败" value="失败" />
        </el-select>
        <el-select v-model="globalKey" placeholder="全部任务" clearable filterable style="width: 210px" @change="onGlobalFilterChange">
          <el-option label="全部任务" value="" />
          <el-option v-for="task in tasks" :key="task.key" :label="task.name" :value="task.key" />
        </el-select>
        <el-tag type="info" effect="plain">共 {{ globalTotal }} 条</el-tag>
        <span class="grow" />
        <el-button size="small" :icon="Refresh" :loading="globalLoading" @click="loadGlobalRuns()">刷新</el-button>
      </div>
      <el-table v-loading="globalLoading" :data="globalRuns" stripe border size="small">
        <el-table-column label="任务" min-width="170">
          <template #default="{ row }">
            <div class="task-name">{{ row.task_name }}</div>
            <div class="task-key mono">{{ row.task_key }}</div>
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="164">
          <template #default="{ row }">
            <span class="mono">{{ fmtDateTime(row.started_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="86" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === '成功' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发方式" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.trigger === '定时' ? 'info' : 'warning'" effect="plain" size="small">
              {{ row.trigger || '手动' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="96" align="right">
          <template #default="{ row }">
            <span class="mono">{{ row.duration_ms != null ? `${row.duration_ms} ms` : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="结果" min-width="260">
          <template #default="{ row }">
            <span :class="{ 'run-error': row.status === '失败' }">
              {{ row.status === '失败' ? row.error || row.result || '执行失败' : row.result || '—' }}
            </span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="globalFailed ? '数据服务暂不可用' : '暂无运行记录'" />
        </template>
      </el-table>
      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="globalPage"
          v-model:page-size="globalPageSize"
          :total="globalTotal"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @current-change="loadGlobalRuns()"
          @size-change="onGlobalSizeChange"
        />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Clock, Refresh } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import api, { type Paged } from '@/api/client'
import { fmtDateTime } from '@/utils/format'

interface TaskRow {
  id: number
  key: string
  name: string
  cron: string
  cron_text?: string
  status: string
  last_run_at?: string | null
  last_result?: string | null
  next_run_at?: string | null
  runs?: number
  description?: string
}

interface TaskRun {
  id: number
  task_id: number
  task_key: string
  task_name: string
  trigger: string
  status: string
  result: string
  error: string
  duration_ms: number
  started_at: string
  finished_at: string
}

const tasks = ref<TaskRow[]>([])
const loading = ref(false)
const runningId = ref<number | null>(null)

const enabledCount = computed(() => tasks.value.filter((item) => item.status === '启用').length)
const pausedCount = computed(() => tasks.value.filter((item) => item.status !== '启用').length)

const runDrawerVisible = ref(false)
const currentTask = ref<TaskRow | null>(null)
const runs = ref<TaskRun[]>([])
const runLoading = ref(false)
const runFailed = ref(false)
const runPage = ref(1)
const runPageSize = ref(10)
const runTotal = ref(0)

const globalVisible = ref(false)
const globalRuns = ref<TaskRun[]>([])
const globalLoading = ref(false)
const globalFailed = ref(false)
const globalPage = ref(1)
const globalPageSize = ref(20)
const globalTotal = ref(0)
const globalStatus = ref('')
const globalKey = ref('')

function warn() {
  ElMessage.warning('数据服务暂不可用')
}

async function load() {
  loading.value = true
  try {
    const list = await api.get<TaskRow[]>('/tasks')
    tasks.value = list || []
  } catch {
    tasks.value = []
    warn()
  } finally {
    loading.value = false
  }
}

async function runNow(row: TaskRow) {
  runningId.value = row.id
  try {
    const res = await api.post<{ ok: boolean; status?: string; result: string; next_run_at?: string }>(
      `/tasks/${row.id}/run`,
    )
    row.last_result = res.result || row.last_result
    row.next_run_at = res.next_run_at || row.next_run_at
    row.runs = (row.runs ?? 0) + 1
    ElMessage.success(res.result || '任务执行完成')
    await load()
    if (runDrawerVisible.value && currentTask.value?.id === row.id) {
      await loadTaskRuns()
    }
    if (globalVisible.value) {
      await loadGlobalRuns()
    }
  } catch {
    warn()
  } finally {
    runningId.value = null
  }
}

async function toggle(row: TaskRow) {
  try {
    const res = await api.post<{ ok: boolean; status: string }>(`/tasks/${row.id}/toggle`)
    row.status = res.status
    ElMessage.success(`任务「${row.name}」已${res.status === '启用' ? '启用' : '暂停'}`)
  } catch {
    warn()
  }
}

async function openTaskRuns(row: TaskRow) {
  currentTask.value = row
  runDrawerVisible.value = true
  runPage.value = 1
  runTotal.value = 0
  runs.value = []
  await loadTaskRuns()
}

async function loadTaskRuns() {
  const task = currentTask.value
  if (!task) return
  runLoading.value = true
  try {
    const result = await api.get<Paged<TaskRun>>(`/tasks/${task.id}/runs`, {
      page: runPage.value,
      page_size: runPageSize.value,
    })
    runs.value = result?.list || []
    runTotal.value = result?.total ?? runs.value.length
    runFailed.value = false
  } catch {
    runs.value = []
    runTotal.value = 0
    runFailed.value = true
    warn()
  } finally {
    runLoading.value = false
  }
}

function onRunSizeChange() {
  runPage.value = 1
  loadTaskRuns()
}

function openGlobalRuns() {
  globalVisible.value = true
  globalPage.value = 1
  globalStatus.value = ''
  globalKey.value = ''
  globalRuns.value = []
  globalTotal.value = 0
  loadGlobalRuns()
}

async function loadGlobalRuns() {
  globalLoading.value = true
  try {
    const params: Record<string, unknown> = {
      page: globalPage.value,
      page_size: globalPageSize.value,
    }
    if (globalStatus.value) params.status = globalStatus.value
    if (globalKey.value) params.key = globalKey.value
    const result = await api.get<Paged<TaskRun>>('/tasks/runs', params)
    globalRuns.value = result?.list || []
    globalTotal.value = result?.total ?? globalRuns.value.length
    globalFailed.value = false
  } catch {
    globalRuns.value = []
    globalTotal.value = 0
    globalFailed.value = true
    warn()
  } finally {
    globalLoading.value = false
  }
}

function onGlobalFilterChange() {
  globalPage.value = 1
  loadGlobalRuns()
}

function onGlobalSizeChange() {
  globalPage.value = 1
  loadGlobalRuns()
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

.task-cron-text {
  font-size: 11px;
  color: #8b9aae;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-toolbar {
  margin-bottom: 12px;
}

.run-error {
  color: #d64545;
}

.page :deep(.el-table) {
  font-size: 13px;
}
</style>
