<template>
  <div class="page">
    <PageHeader title="批量预测" subtitle="一次生成多品种、多地区未来价格预测，支持结果导出">
      <template #actions>
        <el-button
          type="primary"
          :loading="submitting"
          :disabled="submitting || !form.variety_ids.length || !form.region_ids.length"
          @click="submitBatch"
        >
          {{ submitting ? '任务提交中' : '开始批量预测' }}
        </el-button>
        <el-button :loading="exporting" :disabled="exporting || !items.length" @click="exportCsv">
          导出 CSV
        </el-button>
      </template>
    </PageHeader>

    <div class="page-card">
      <div class="card-title">
        <span>任务设置</span>
        <span class="muted condition-hint">按品种与地区的组合逐个生成预测</span>
      </div>
      <el-form label-width="84px">
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="品种">
              <el-select
                v-model="form.variety_ids"
                multiple
                collapse-tags
                collapse-tags-tooltip
                filterable
                placeholder="请选择品种（可多选）"
                style="width: 100%"
              >
                <el-option
                  v-for="item in dicts?.varieties || []"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="地区">
              <el-select
                v-model="form.region_ids"
                multiple
                collapse-tags
                collapse-tags-tooltip
                filterable
                placeholder="请选择地区（可多选）"
                style="width: 100%"
              >
                <el-option
                  v-for="item in dicts?.regions || []"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="4">
            <el-form-item label="预测天数">
              <el-input-number
                v-model="form.horizon"
                :min="1"
                :max="90"
                :step="1"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="4">
            <el-form-item label="组合数量">
              <div class="combo-count">
                <span class="combo-value">{{ form.variety_ids.length * form.region_ids.length }}</span>
                <span class="muted">个组合</span>
              </div>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <div class="muted condition-tip">
        任务提交后页面会自动轮询进度；组合数量较多时耗时较长，请保持页面打开直至任务结束。
      </div>
    </div>

    <template v-if="batch">
      <div class="kpi-grid">
        <KpiCard label="任务编号" :value="batch.batch_id" icon="Tickets" tone="blue" hint="本次批量预测任务" />
        <KpiCard label="预测组合" :value="batch.total" unit="个" icon="Grid" tone="purple" />
        <KpiCard label="已完成" :value="batch.done" unit="个" icon="CircleCheck" tone="green" />
        <KpiCard
          label="任务状态"
          :value="statusLabel"
          icon="Loading"
          :tone="statusTone"
          :hint="batch.created_at ? `创建于 ${fmtDateTime(batch.created_at)}` : ''"
        />
      </div>

      <div class="page-card">
        <div class="card-title">
          <span>执行进度</span>
          <span class="muted condition-hint">{{ pollHint }}</span>
        </div>
        <el-progress
          :percentage="percent"
          :status="progressStatus"
          :stroke-width="14"
          :striped="!terminal"
          :striped-flow="!terminal"
        />
        <div class="progress-meta">
          <el-tag :type="statusTagType" effect="plain">{{ statusLabel }}</el-tag>
          <span class="muted">已完成 {{ batch.done }} / {{ batch.total }} 个组合</span>
          <span class="muted">预测天数 {{ batch.horizon || form.horizon }} 天</span>
          <span v-if="batch.created_by" class="muted">提交人 {{ batch.created_by }}</span>
          <span v-if="terminal && !polling" class="muted">任务已结束</span>
        </div>
      </div>

      <div class="page-card">
        <div class="card-title">
          <span>预测结果</span>
          <span class="muted condition-hint">共 {{ items.length }} 条</span>
        </div>
        <el-table :data="items" size="small" stripe max-height="480" v-loading="polling && !items.length">
          <el-table-column prop="variety" label="品种" min-width="96" show-overflow-tooltip />
          <el-table-column prop="region" label="地区" min-width="100" show-overflow-tooltip />
          <el-table-column label="预测价格" min-width="100" align="right">
            <template #default="{ row }">{{ fmtNum(row.point, 2) }}</template>
          </el-table-column>
          <el-table-column label="置信区间" min-width="156" align="right">
            <template #default="{ row }">{{ fmtNum(row.lower, 2) }} ~ {{ fmtNum(row.upper, 2) }}</template>
          </el-table-column>
          <el-table-column label="方向" width="84" align="center">
            <template #default="{ row }">
              <el-tag :type="directionTagType(row.direction)" size="small" effect="plain">
                {{ directionLabel(row.direction) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="MAPE" width="96" align="right">
            <template #default="{ row }">{{ fmtNum(row.mape, 2) }}%</template>
          </el-table-column>
          <template #empty>
            <el-empty :description="terminal ? '本次任务暂无预测结果' : '任务执行中，请稍候'" :image-size="64" />
          </template>
        </el-table>
      </div>
    </template>

    <div v-else class="page-card">
      <el-empty description="设置品种、地区与预测天数后提交批量任务" :image-size="96" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import KpiCard from '@/components/KpiCard.vue'
import api from '@/api/client'
import { fmtDateTime, fmtNum } from '@/utils/format'
import type { MetaDicts } from '@/types'

interface BatchItem {
  variety_id?: number
  variety: string
  region_id?: number
  region: string
  point: number
  direction: string
  lower: number
  upper: number
  mape: number
}

interface BatchDetail {
  batch_id: number
  status: string
  done: number
  total: number
  horizon?: number
  created_by?: string
  created_at: string
  items: BatchItem[]
  errors?: string[]
}

interface BatchCreated {
  batch_id: number
  total: number
  status: string
  done: number
  created_at: string
  errors?: string[]
}

const POLL_INTERVAL = 1500
const MAX_POLLS = 90

const dicts = ref<MetaDicts | null>(null)
const batch = ref<BatchDetail | null>(null)
const submitting = ref(false)
const exporting = ref(false)
const polling = ref(false)

const form = reactive<{ variety_ids: number[]; region_ids: number[]; horizon: number }>({
  variety_ids: [],
  region_ids: [],
  horizon: 14,
})

let timer: ReturnType<typeof setInterval> | null = null
let pollAttempts = 0
let pollRequesting = false

const items = computed<BatchItem[]>(() => batch.value?.items || [])

const terminal = computed(() => {
  const status = batch.value?.status
  return status === '已完成' || status === '部分完成' || status === '失败'
})

const statusLabel = computed(() => {
  const status = batch.value?.status
  if (!status) return '排队中'
  if (status === '处理中' || status === '执行中') return '执行中'
  if (status === '已完成' || status === '部分完成' || status === '失败') return status
  return status
})

const statusTagType = computed<'warning' | 'success' | 'danger' | 'info'>(() => {
  const status = batch.value?.status
  if (status === '已完成' || status === '部分完成') return 'success'
  if (status === '失败') return 'danger'
  if (status === '处理中' || status === '执行中') return 'warning'
  return 'info'
})

const statusTone = computed<'blue' | 'green' | 'orange' | 'red'>(() => {
  const status = batch.value?.status
  if (status === '已完成') return 'green'
  if (status === '部分完成') return 'orange'
  if (status === '失败') return 'red'
  return 'blue'
})

const percent = computed(() => {
  const current = batch.value
  if (!current) return 0
  if (!current.total) return current.status === '已完成' ? 100 : 0
  return Math.min(100, Math.round((current.done / current.total) * 100))
})

const progressStatus = computed<'' | 'success' | 'exception' | 'warning'>(() => {
  const status = batch.value?.status
  if (status === '已完成') return 'success'
  if (status === '部分完成') return 'warning'
  if (status === '失败') return 'exception'
  return ''
})

const pollHint = computed(() => {
  if (polling.value) return '正在轮询任务状态…'
  if (terminal.value) return '任务已结束'
  return '等待任务执行'
})

function directionLabel(direction?: string): string {
  if (!direction) return '—'
  if (direction === '震荡' || direction === '持平') return '持平'
  return direction
}

function directionTagType(direction?: string): 'danger' | 'success' | 'info' {
  if (direction === '上涨') return 'danger'
  if (direction === '下跌') return 'success'
  return 'info'
}

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  polling.value = false
}

function finishPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  polling.value = false
}

async function loadDicts() {
  dicts.value = await api.get<MetaDicts>('/meta/dicts')
}

function startPolling(batchId: number) {
  stopPolling()
  pollAttempts = 0
  polling.value = true
  void pollOnce(batchId)
  timer = setInterval(() => {
    void pollOnce(batchId)
  }, POLL_INTERVAL)
}

async function pollOnce(batchId: number) {
  if (pollRequesting || !polling.value) return
  pollAttempts += 1
  if (pollAttempts > MAX_POLLS) {
    stopPolling()
    ElMessage.warning('任务查询超时，请稍后刷新重试')
    return
  }
  pollRequesting = true
  try {
    const data = await api.get<BatchDetail>(`/forecast/batch/${batchId}`)
    batch.value = {
      ...(batch.value as BatchDetail),
      ...data,
      items: data.items || [],
    }
    if (data.status === '已完成' || data.status === '部分完成' || data.status === '失败') {
      finishPolling()
      if (data.status === '失败') ElMessage.warning('批量预测任务执行失败')
      else if (data.status === '部分完成') ElMessage.warning('批量预测已完成，部分组合未生成结果')
      else ElMessage.success('批量预测完成')
    }
  } catch {
    stopPolling()
    ElMessage.warning('数据服务暂不可用')
  } finally {
    pollRequesting = false
  }
}

async function submitBatch() {
  if (!form.variety_ids.length || !form.region_ids.length) {
    ElMessage.warning('请选择品种和地区')
    return
  }
  submitting.value = true
  stopPolling()
  batch.value = null
  try {
    const created = await api.post<BatchCreated>('/forecast/batch', {
      variety_ids: form.variety_ids,
      region_ids: form.region_ids,
      horizon: form.horizon,
    })
    batch.value = {
      batch_id: created.batch_id,
      status: created.status || '处理中',
      done: created.done || 0,
      total: created.total || 0,
      horizon: form.horizon,
      created_at: created.created_at || new Date().toISOString(),
      items: [],
    }
    ElMessage.success('批量任务已提交')
    startPolling(created.batch_id)
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    submitting.value = false
  }
}

async function exportCsv() {
  const batchId = batch.value?.batch_id
  if (!batchId || !items.value.length) {
    ElMessage.warning('暂无可导出的预测结果')
    return
  }
  exporting.value = true
  try {
    await api.download(`/forecast/batch/${batchId}/export`, {}, '批量预测.csv')
    ElMessage.success('导出已开始')
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  try {
    await loadDicts()
  } catch {
    ElMessage.warning('数据服务暂不可用')
  }
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.condition-hint {
  font-size: 12px;
  font-weight: 400;
}

.condition-tip {
  font-size: 12px;
  line-height: 1.7;
}

.combo-count {
  display: flex;
  align-items: baseline;
  gap: 6px;
  height: 32px;
}

.combo-value {
  font-size: 20px;
  font-weight: 600;
  color: #1f5fd6;
  font-variant-numeric: tabular-nums;
}

.progress-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 18px;
  margin-top: 14px;
  font-size: 13px;
}
</style>
