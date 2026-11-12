<template>
  <div class="page">
    <PageHeader title="预警信息" subtitle="监控价格异常波动，及时处置风险预警">
      <template #actions>
        <el-tooltip :disabled="canHandle" content="暂无预警处置权限，无法执行扫描" placement="bottom">
          <span>
            <el-button type="primary" :loading="scanning" :disabled="!canHandle || scanning" @click="runScan">
              {{ scanning ? '扫描中' : '立即扫描' }}
            </el-button>
          </span>
        </el-tooltip>
      </template>
    </PageHeader>

    <div class="kpi-grid">
      <KpiCard
        label="未处置预警"
        :value="stats?.open_count ?? '—'"
        icon="WarningFilled"
        tone="red"
        :hint="levelHint"
        clickable
        @click="quickFilterOpen"
      />
      <KpiCard
        label="近 30 天预警"
        :value="stats?.total_30d ?? '—'"
        icon="Bell"
        tone="blue"
        hint="含已关闭预警"
      />
      <KpiCard
        label="处置率"
        :value="fmtNum(stats?.recall_rate, 1)"
        unit="%"
        icon="CircleCheck"
        tone="green"
        hint="已处置预警占比"
      />
      <KpiCard
        label="误报率"
        :value="fmtNum(stats?.false_positive_rate, 1)"
        unit="%"
        icon="Warning"
        tone="orange"
        hint="误报预警占比"
      />
    </div>

    <div class="page-card">
      <div class="toolbar">
        <el-select v-model="filters.status" clearable placeholder="处置状态" style="width: 140px" @change="applyFilters">
          <el-option v-for="item in statusOptions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="filters.level" clearable placeholder="预警级别" style="width: 130px" @change="applyFilters">
          <el-option v-for="item in levelOptions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select
          v-model="filters.variety_id"
          clearable
          filterable
          placeholder="品种"
          style="width: 150px"
          @change="applyFilters"
        >
          <el-option
            v-for="item in dicts?.varieties || []"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>
        <el-select
          v-model="filters.region_id"
          clearable
          filterable
          placeholder="地区"
          style="width: 150px"
          @change="applyFilters"
        >
          <el-option
            v-for="item in dicts?.regions || []"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>
        <el-button type="primary" @click="applyFilters">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <span class="grow" />
        <span class="muted result-count">共 {{ total }} 条预警</span>
      </div>

      <el-table :data="list" size="small" stripe max-height="620" v-loading="loading">
        <el-table-column label="预警标题" min-width="230">
          <template #default="{ row }">
            <div class="alert-title" @click="openDetail(row)">{{ row.title }}</div>
            <div class="muted alert-sub">{{ row.rule_name || '规则触发' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="级别" width="82" align="center">
          <template #default="{ row }">
            <el-tag :type="levelTagType(row.level)" size="small" effect="dark">{{ row.level }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="variety" label="品种" min-width="86" show-overflow-tooltip />
        <el-table-column prop="region" label="地区" min-width="90" show-overflow-tooltip />
        <el-table-column label="预警日期" width="110">
          <template #default="{ row }">{{ fmtDate(row.alert_date) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="92" align="center">
          <template #default="{ row }">
            <el-tag :type="alertStatusType(row.status)" size="small" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="处置人" min-width="88">
          <template #default="{ row }">{{ row.handler || '—' }}</template>
        </el-table-column>
        <el-table-column label="处置时间" min-width="148">
          <template #default="{ row }">{{ fmtDateTime(row.handled_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="128" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
            <el-tooltip :disabled="canHandle || row.status === '已关闭'" content="暂无预警处置权限" placement="top">
              <span class="handle-wrap">
                <el-button
                  link
                  type="primary"
                  size="small"
                  :disabled="!canHandle || row.status === '已关闭'"
                  @click="openHandle(row)"
                >
                  处置
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无符合条件的预警" :image-size="64" />
        </template>
      </el-table>

      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :page-sizes="[10, 15, 20, 50]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="loadList"
          @size-change="handleSizeChange"
        />
      </div>
    </div>

    <el-drawer v-model="detailVisible" title="预警详情" size="520px">
      <template v-if="detail">
        <div class="detail-head">
          <el-tag :type="levelTagType(detail.level)" effect="dark">{{ detail.level }}级预警</el-tag>
          <el-tag :type="alertStatusType(detail.status)" effect="plain">{{ detail.status }}</el-tag>
          <span class="muted">{{ fmtDateTime(detail.created_at) }}</span>
        </div>
        <h3 class="detail-title">{{ detail.title }}</h3>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="品种">{{ detail.variety || '—' }}</el-descriptions-item>
          <el-descriptions-item label="地区">{{ detail.region || '—' }}</el-descriptions-item>
          <el-descriptions-item label="触发规则">{{ detail.rule_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="预警日期">{{ fmtDate(detail.alert_date) }}</el-descriptions-item>
          <el-descriptions-item label="通知渠道">{{ parseChannelText(detail.notify_channel) }}</el-descriptions-item>
          <el-descriptions-item label="处置人">{{ detail.handler || '—' }}</el-descriptions-item>
          <el-descriptions-item label="处置时间">{{ fmtDateTime(detail.handled_at) }}</el-descriptions-item>
        </el-descriptions>
        <div class="detail-block">
          <div class="detail-label">预警说明</div>
          <div class="detail-text">{{ detail.detail || '—' }}</div>
        </div>
        <div v-if="detail.handle_note" class="detail-block">
          <div class="detail-label">处置说明</div>
          <div class="detail-text">{{ detail.handle_note }}</div>
        </div>
        <div class="detail-actions">
          <el-button @click="detailVisible = false">关闭</el-button>
          <el-button
            v-if="detail.status !== '已关闭'"
            type="primary"
            :disabled="!canHandle"
            @click="openHandle(detail)"
          >
            处置
          </el-button>
        </div>
      </template>
      <el-empty v-else description="暂无预警详情" />
    </el-drawer>

    <el-dialog v-model="handleVisible" title="预警处置" width="540px" top="10vh">
      <el-alert
        v-if="handleAlert"
        :title="handleAlert.title"
        type="warning"
        :closable="false"
        show-icon
        class="handle-alert"
      />
      <el-form ref="handleFormRef" :model="handleForm" :rules="handleRules" label-width="92px" class="handle-form">
        <el-form-item label="处置方式">
          <el-radio-group v-model="handleForm.action" @change="handleActionChange">
            <el-radio value="ack">确认处置（处理中）</el-radio>
            <el-radio value="close">关闭预警（已关闭）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="处置说明" prop="note">
          <el-input
            v-model="handleForm.note"
            type="textarea"
            :rows="3"
            maxlength="300"
            show-word-limit
            placeholder="请填写处置说明，例如已通知相关市场核实价格"
          />
        </el-form-item>
        <el-form-item v-if="handleForm.action === 'close'" label="处置结果" prop="result">
          <el-input
            v-model="handleForm.result"
            type="textarea"
            :rows="3"
            maxlength="300"
            show-word-limit
            placeholder="请填写最终处置结果"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="handleVisible = false">取消</el-button>
        <el-button type="primary" :loading="handleSubmitting" @click="submitHandle">提交处置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import KpiCard from '@/components/KpiCard.vue'
import api from '@/api/client'
import type { Paged } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import {
  alertStatusType,
  fmtDate,
  fmtDateTime,
  fmtNum,
  levelTagType,
} from '@/utils/format'
import type { MetaDicts } from '@/types'

interface AlertItem {
  id: number
  level: string
  title: string
  variety_id?: number
  variety: string
  region_id?: number
  region: string
  alert_date: string
  status: string
  rule_name?: string
  detail?: string
  handler?: string
  handled_at?: string
  handle_note?: string
  notify_channel?: string
  created_at?: string
}

interface AlertStats {
  open_count: number
  total_30d: number
  by_level: Array<{ level: string; count: number }>
  by_status?: Array<{ status: string; count: number }>
  trend?: Array<{ date: string; count: number }>
  recall_rate: number
  false_positive_rate: number
}

interface EvaluateResult {
  created: number
  scanned: number
  rules: number
}

const auth = useAuthStore()
const canHandle = computed(() => auth.hasPerm('alert:handle'))

const dicts = ref<MetaDicts | null>(null)
const list = ref<AlertItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(15)
const loading = ref(false)
const stats = ref<AlertStats | null>(null)
const scanning = ref(false)

const filters = reactive<{
  status: string | null
  level: string | null
  variety_id: number | null
  region_id: number | null
}>({
  status: null,
  level: null,
  variety_id: null,
  region_id: null,
})

const detailVisible = ref(false)
const detail = ref<AlertItem | null>(null)

const handleVisible = ref(false)
const handleSubmitting = ref(false)
const handleAlert = ref<AlertItem | null>(null)
const handleFormRef = ref<FormInstance>()
const handleForm = reactive<{ action: 'ack' | 'close'; note: string; result: string }>({
  action: 'ack',
  note: '',
  result: '',
})

const statusOptions = ['待处理', '处理中', '已关闭']
const levelOptions = computed(() => {
  const levels = dicts.value?.alert_levels || []
  return levels.length ? levels : ['高', '中', '低']
})

const levelHint = computed(() => {
  const rows = stats.value?.by_level || []
  if (!rows.length) return '按预警级别统计'
  return rows.map((item) => `${item.level} ${item.count}`).join(' · ')
})

const handleRules: FormRules = {
  note: [
    { required: true, message: '请填写处置说明', trigger: 'blur' },
    { min: 2, message: '处置说明至少填写 2 个字', trigger: 'blur' },
  ],
  result: [
    {
      validator: (_rule, value, callback) => {
        if (handleForm.action === 'close' && !String(value || '').trim()) {
          callback(new Error('关闭预警时请填写处置结果'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
}

function parseChannelText(channel?: string): string {
  if (!channel) return '站内消息'
  const text = String(channel).trim()
  if (!text) return '站内消息'
  if (text.startsWith('[')) {
    try {
      const parsed = JSON.parse(text)
      if (Array.isArray(parsed)) {
        const names = parsed.map((item) => String(item)).filter(Boolean)
        return names.length ? names.join('、') : '站内消息'
      }
    } catch {
      /* 非 JSON 渠道按普通文本展示 */
    }
  }
  return text.replace(/[,，]/g, '、')
}

async function loadDicts() {
  dicts.value = await api.get<MetaDicts>('/meta/dicts')
}

async function fetchList() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (filters.status) params.status = filters.status
    if (filters.level) params.level = filters.level
    if (filters.variety_id) params.variety_id = filters.variety_id
    if (filters.region_id) params.region_id = filters.region_id
    const data = await api.get<Paged<AlertItem>>('/alerts', params)
    list.value = data.list || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  stats.value = await api.get<AlertStats>('/alerts/statistics')
}

async function refreshAll() {
  const results = await Promise.allSettled([fetchList(), fetchStats()])
  if (results.some((item) => item.status === 'rejected')) {
    ElMessage.warning('数据服务暂不可用')
  }
}

async function loadList() {
  try {
    await fetchList()
  } catch {
    ElMessage.warning('数据服务暂不可用')
  }
}

function applyFilters() {
  page.value = 1
  loadList()
}

function resetFilters() {
  filters.status = null
  filters.level = null
  filters.variety_id = null
  filters.region_id = null
  page.value = 1
  loadList()
}

function quickFilterOpen() {
  filters.status = '待处理'
  page.value = 1
  loadList()
}

function handleSizeChange(size: number) {
  pageSize.value = size
  page.value = 1
  loadList()
}

function openDetail(row: AlertItem) {
  detail.value = row
  detailVisible.value = true
}

function openHandle(row: AlertItem) {
  if (!canHandle.value || row.status === '已关闭') return
  handleAlert.value = row
  handleForm.action = row.status === '处理中' ? 'close' : 'ack'
  handleForm.note = ''
  handleForm.result = ''
  handleVisible.value = true
  nextTick(() => handleFormRef.value?.clearValidate())
}

function handleActionChange() {
  nextTick(() => handleFormRef.value?.clearValidate('result'))
}

async function submitHandle() {
  const formEl = handleFormRef.value
  if (!formEl) return
  try {
    await formEl.validate()
  } catch {
    return
  }
  const target = handleAlert.value
  if (!target) return
  handleSubmitting.value = true
  try {
    if (handleForm.action === 'close') {
      await api.post(`/alerts/${target.id}/close`, {
        note: handleForm.note.trim(),
        result: handleForm.result.trim(),
      })
      ElMessage.success('预警已关闭')
    } else {
      await api.post(`/alerts/${target.id}/ack`, { note: handleForm.note.trim() })
      ElMessage.success('已提交处置')
    }
    handleVisible.value = false
    detailVisible.value = false
    await refreshAll()
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    handleSubmitting.value = false
  }
}

async function runScan() {
  if (!canHandle.value) return
  scanning.value = true
  try {
    const result = await api.post<EvaluateResult>('/alerts/evaluate')
    ElMessage.success(`扫描完成，新增预警 ${result.created} 条`)
    await refreshAll()
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    scanning.value = false
  }
}

onMounted(async () => {
  const results = await Promise.allSettled([loadDicts(), fetchList(), fetchStats()])
  if (results.some((item) => item.status === 'rejected')) {
    ElMessage.warning('数据服务暂不可用')
  }
})
</script>

<style scoped>
.result-count {
  font-size: 12px;
}

.alert-title {
  font-weight: 500;
  color: #1c2a3a;
  cursor: pointer;
  line-height: 1.5;
}

.alert-title:hover {
  color: #1f5fd6;
}

.alert-sub {
  margin-top: 2px;
  font-size: 11px;
}

.handle-wrap {
  display: inline-block;
  margin-left: 6px;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
}

.detail-title {
  margin: 12px 0;
  font-size: 16px;
  font-weight: 600;
  color: #1c2a3a;
}

.detail-block {
  margin-top: 16px;
}

.detail-label {
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #40536b;
}

.detail-text {
  padding: 10px 12px;
  border-radius: 8px;
  background: #f7f9fd;
  font-size: 13px;
  line-height: 1.7;
  color: #40536b;
  white-space: pre-wrap;
  word-break: break-word;
}

.detail-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 22px;
}

.handle-alert {
  margin-bottom: 16px;
}

.handle-form {
  margin-top: 4px;
}
</style>
