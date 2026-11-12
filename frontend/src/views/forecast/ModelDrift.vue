<template>
  <div class="page">
    <PageHeader title="模型监测" subtitle="监控模型精度衰减与特征分布漂移，支持模型对比与快速重训">
      <template #actions>
        <el-button :icon="Refresh" :loading="loading" @click="refreshAll">刷新</el-button>
      </template>
    </PageHeader>

    <div class="kpi-grid">
      <KpiCard
        label="模型总数"
        :value="summary.total ?? '—'"
        unit="个"
        icon="Cpu"
        tone="blue"
        :hint="totalHint"
      />
      <KpiCard
        label="平稳模型"
        :value="summary.stable ?? '—'"
        unit="个"
        icon="CircleCheck"
        tone="green"
        :hint="stableHint"
      />
      <KpiCard
        label="需关注"
        :value="summary.watch ?? '—'"
        unit="个"
        icon="Warning"
        tone="orange"
        :hint="watchHint"
      />
      <KpiCard
        label="已漂移"
        :value="summary.drifted ?? '—'"
        unit="个"
        icon="WarningFilled"
        tone="red"
        :hint="driftedHint"
      />
    </div>

    <div class="drift-layout">
      <section class="page-card table-card">
        <div class="toolbar">
          <el-select
            v-model="filterVariety"
            clearable
            filterable
            placeholder="全部品种"
            style="width: 132px"
            @change="onFilterChange"
          >
            <el-option v-for="item in varietyOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select
            v-model="filterRegion"
            clearable
            filterable
            placeholder="全部地区"
            style="width: 132px"
            @change="onFilterChange"
          >
            <el-option v-for="item in regionOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select
            v-model="filterLevel"
            clearable
            placeholder="全部漂移等级"
            style="width: 142px"
            @change="onFilterChange"
          >
            <el-option v-for="item in driftLevels" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select v-model="windowDays" style="width: 138px" @change="loadDrift">
            <el-option v-for="item in windowOptions" :key="item" :label="`基准窗口 ${item} 天`" :value="item" />
          </el-select>
          <span class="muted">共 {{ filteredItems.length }} 个模型</span>
          <div class="grow" />
          <span v-if="selected" class="muted selected-hint">已选：{{ selected.variety }} · {{ selected.region }}</span>
        </div>

        <el-table
          v-loading="loading"
          :data="filteredItems"
          size="small"
          stripe
          height="528"
          highlight-current-row
          :row-class-name="rowClassName"
          @row-click="onRowClick"
        >
          <el-table-column label="模型" min-width="184" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="model-name">{{ row.name }}</div>
              <div class="muted model-key mono">{{ row.key }}</div>
            </template>
          </el-table-column>
          <el-table-column label="算法" width="104">
            <template #default="{ row }">
              <el-tag type="info" effect="plain" size="small">{{ algorithmLabel(row.algorithm) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="variety" label="品种" width="82" show-overflow-tooltip />
          <el-table-column prop="region" label="地区" width="88" show-overflow-tooltip />
          <el-table-column label="MAPE" width="82" align="right">
            <template #default="{ row }">{{ fmtPct(row.mape, 2, false) }}</template>
          </el-table-column>
          <el-table-column label="近期 MAPE" width="98" align="right">
            <template #default="{ row }">{{ fmtPct(row.recent_mape, 2, false) }}</template>
          </el-table-column>
          <el-table-column label="变化" width="82" align="right">
            <template #default="{ row }">
              <span :class="changeClass(row.mape_change)">{{ fmtPct(row.mape_change, 2, true) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="PSI" width="74" align="right">
            <template #default="{ row }"><span class="mono">{{ fmtNum(row.psi, 3) }}</span></template>
          </el-table-column>
          <el-table-column label="漂移等级" width="92" align="center">
            <template #default="{ row }">
              <el-tag :type="driftTagType(row.drift_level)" size="small" effect="dark">
                {{ row.drift_level || '—' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="训练时间" width="146">
            <template #default="{ row }">{{ fmtDateTime(row.trained_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="116" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="selectModel(row)">对比</el-button>
              <el-tooltip
                :disabled="canTrainRow(row)"
                content="暂无模型管理权限，或缺少品种 / 地区标识"
                placement="top"
              >
                <span>
                  <el-button
                    link
                    type="warning"
                    size="small"
                    :disabled="!canTrainRow(row)"
                    :loading="trainingId === row.model_id"
                    @click.stop="retrain(row)"
                  >
                    重训
                  </el-button>
                </span>
              </el-tooltip>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无模型漂移数据" :image-size="64" />
          </template>
        </el-table>
      </section>

      <section class="page-card compare-card">
        <div class="card-title">
          <span>算法对比</span>
          <span v-if="selected" class="muted compare-sub">{{ selected.variety }} · {{ selected.region }}</span>
        </div>

        <template v-if="selected">
          <div class="psi-panel">
            <div class="psi-head">
              <span class="psi-label">PSI 漂移指数</span>
              <el-tag :type="driftTagType(selected.drift_level)" size="small" effect="dark">
                {{ selected.drift_level || '—' }}
              </el-tag>
            </div>
            <div class="psi-value-row">
              <span class="psi-value">{{ fmtNum(selected.psi, 3) }}</span>
              <span class="muted psi-threshold">关注阈值 0.10 · 漂移阈值 0.25</span>
            </div>
            <el-progress :percentage="psiPercent" :stroke-width="8" :show-text="false" :color="psiColor" />
            <div class="psi-rules">
              <span><i class="dot dot-stable" />PSI &lt; 0.10 平稳</span>
              <span><i class="dot dot-watch" />0.10 ~ 0.25 关注</span>
              <span><i class="dot dot-drift" />&gt; 0.25 漂移</span>
            </div>
            <div class="psi-meta">
              <span>近期 MAPE：<b>{{ fmtPct(selected.recent_mape, 2, false) }}</b></span>
              <span>变化：<b :class="changeClass(selected.mape_change)">{{ fmtPct(selected.mape_change, 2, true) }}</b></span>
              <span>最近检查：{{ fmtDateTime(selected.last_checked_at) }}</span>
            </div>
            <p class="psi-tip">
              PSI 基于特征波动率近 30 天分布与基准窗口对比计算，数值越大表示分布偏移越明显；处于关注或漂移状态时建议重训模型。
            </p>
          </div>

          <div class="compare-block">
            <div class="compare-title">MAPE 对比 <span class="muted">（越低越好）</span></div>
            <BaseChart
              :option="compareMapeOption"
              :height="204"
              :loading="compareLoading"
              :empty="!compareLoading && !compareRows.length"
              :empty-text="compareEmptyText"
            />
          </div>

          <div class="compare-block">
            <div class="compare-title">方向准确率对比 <span class="muted">（越高越好）</span></div>
            <BaseChart
              :option="compareAccOption"
              :height="204"
              :loading="compareLoading"
              :empty="!compareLoading && !compareRows.length"
              :empty-text="compareEmptyText"
            />
          </div>
        </template>
        <el-empty v-else description="点击左侧模型行查看算法对比与 PSI 说明" :image-size="72" />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import PageHeader from '@/components/PageHeader.vue'
import KpiCard from '@/components/KpiCard.vue'
import BaseChart from '@/components/BaseChart.vue'
import api from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { fmtDateTime, fmtNum, fmtPct } from '@/utils/format'
import type { MetaDicts } from '@/types'

interface DriftItem {
  model_id: number
  key: string
  name: string
  algorithm: string
  variety: string
  region: string
  status?: string
  mape: number
  recent_mape: number
  psi: number
  drift_level: string
  mape_change: number
  trained_at?: string
  last_checked_at?: string
}

interface DriftSummary {
  total: number
  stable: number
  watch: number
  drifted: number
  avg_psi: number
}

interface DriftData {
  items: DriftItem[]
  summary?: DriftSummary
  window?: number
  checked_at?: string
}

interface CompareRow {
  key: string
  name: string
  algorithm: string
  mape: number
  rmse: number
  direction_acc: number
  is_active: boolean
  trained_at?: string
}

const ALGORITHM_LABELS: Record<string, string> = {
  ensemble: '组合模型',
  gbr: '梯度提升',
  seasonal: '季节分解',
  holt_winters: 'Holt-Winters',
}

const driftLevels = ['平稳', '关注', '漂移']
const windowOptions = [30, 60, 90]

const auth = useAuthStore()
const canManage = computed(() => auth.hasPerm('model:manage'))

const loading = ref(false)
const driftItems = ref<DriftItem[]>([])
const summary = ref<Partial<DriftSummary>>({})
const checkedAt = ref('')
const windowDays = ref(90)

const filterVariety = ref('')
const filterRegion = ref('')
const filterLevel = ref('')

const selectedId = ref<number | null>(null)
const compareRows = ref<CompareRow[]>([])
const compareLoading = ref(false)
const compareMissing = ref(false)
const trainingId = ref<number | null>(null)

const dicts = ref<MetaDicts | null>(null)

const varietyOptions = computed(() => {
  const names = driftItems.value.map((item) => item.variety).filter(Boolean)
  return Array.from(new Set(names)).sort()
})

const regionOptions = computed(() => {
  const names = driftItems.value.map((item) => item.region).filter(Boolean)
  return Array.from(new Set(names)).sort()
})

const filteredItems = computed(() =>
  driftItems.value.filter((item) => {
    if (filterVariety.value && item.variety !== filterVariety.value) return false
    if (filterRegion.value && item.region !== filterRegion.value) return false
    if (filterLevel.value && item.drift_level !== filterLevel.value) return false
    return true
  }),
)

const selected = computed(() => driftItems.value.find((item) => item.model_id === selectedId.value) || null)

const varietyIdByName = computed(() => {
  const map = new Map<string, number>()
  for (const item of dicts.value?.varieties || []) map.set(item.name, item.id)
  return map
})

const regionIdByName = computed(() => {
  const map = new Map<string, number>()
  for (const item of dicts.value?.regions || []) map.set(item.name, item.id)
  return map
})

const totalHint = computed(() =>
  summary.value.avg_psi != null ? `平均 PSI ${fmtNum(summary.value.avg_psi, 3)}` : '漂移检测模型总数',
)

const stableHint = computed(() => {
  const total = Number(summary.value.total || 0)
  const stable = Number(summary.value.stable || 0)
  return total > 0 ? `占比 ${fmtPct((stable / total) * 100, 1, false)}` : '分布稳定'
})

const watchHint = computed(() => {
  if (checkedAt.value) return `检查于 ${fmtDateTime(checkedAt.value)}`
  return '精度或特征分布需观察'
})

const driftedHint = computed(() => (Number(summary.value.drifted || 0) > 0 ? '建议尽快重训' : '暂无漂移模型'))

const psiPercent = computed(() => {
  const psi = Number(selected.value?.psi ?? 0)
  if (!Number.isFinite(psi)) return 0
  return Math.max(0, Math.min(100, Math.round((psi / 0.5) * 100)))
})

const psiColor = computed(() => {
  const level = selected.value?.drift_level
  if (level === '平稳') return '#1c9c6b'
  if (level === '关注') return '#e6a23c'
  if (level === '漂移') return '#d64545'
  return '#1f5fd6'
})

const compareEmptyText = computed(() =>
  compareMissing.value ? '缺少品种或地区标识，无法加载算法对比' : '该品种地区暂无算法对比数据',
)

const compareMapeOption = computed<EChartsOption>(() => ({
  grid: { left: 6, right: 52, top: 8, bottom: 2, containLabel: true },
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    valueFormatter: (value) => `${fmtNum(Number(value), 2)}%`,
  },
  xAxis: {
    type: 'value',
    axisLabel: { formatter: '{value}%', color: '#8b9aae', fontSize: 11 },
    splitLine: { lineStyle: { color: '#eef2f8' } },
  },
  yAxis: {
    type: 'category',
    inverse: true,
    data: compareRows.value.map((item) => algorithmLabel(item.algorithm)),
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: { color: '#5b6b7f', fontSize: 12 },
  },
  series: [
    {
      type: 'bar',
      name: 'MAPE',
      data: compareRows.value.map((item) => item.mape),
      barMaxWidth: 18,
      itemStyle: { color: '#1f5fd6', borderRadius: [0, 4, 4, 0] },
      label: {
        show: true,
        position: 'right',
        color: '#40536b',
        fontSize: 11,
        formatter: (params: any) => `${fmtNum(Number(params.value), 2)}%`,
      },
    },
  ],
}))

const compareAccOption = computed<EChartsOption>(() => ({
  grid: { left: 6, right: 52, top: 8, bottom: 2, containLabel: true },
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    valueFormatter: (value) => `${fmtNum(Number(value), 1)}%`,
  },
  xAxis: {
    type: 'value',
    max: 100,
    axisLabel: { formatter: '{value}%', color: '#8b9aae', fontSize: 11 },
    splitLine: { lineStyle: { color: '#eef2f8' } },
  },
  yAxis: {
    type: 'category',
    inverse: true,
    data: compareRows.value.map((item) => algorithmLabel(item.algorithm)),
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: { color: '#5b6b7f', fontSize: 12 },
  },
  series: [
    {
      type: 'bar',
      name: '方向准确率',
      data: compareRows.value.map((item) => item.direction_acc),
      barMaxWidth: 18,
      itemStyle: { color: '#1c9c6b', borderRadius: [0, 4, 4, 0] },
      label: {
        show: true,
        position: 'right',
        color: '#40536b',
        fontSize: 11,
        formatter: (params: any) => `${fmtNum(Number(params.value), 1)}%`,
      },
    },
  ],
}))

function algorithmLabel(algorithm?: string): string {
  if (!algorithm) return '—'
  return ALGORITHM_LABELS[algorithm] || algorithm
}

function driftTagType(level?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (level === '平稳') return 'success'
  if (level === '关注') return 'warning'
  if (level === '漂移') return 'danger'
  return 'info'
}

function changeClass(change?: number): string {
  const num = Number(change)
  if (!Number.isFinite(num) || num === 0) return ''
  return num > 0 ? 'text-up' : 'text-down'
}

function rowClassName({ row }: { row: DriftItem }): string {
  return row.model_id === selectedId.value ? 'selected-row' : ''
}

function onFilterChange() {
  if (selected.value && !filteredItems.value.some((item) => item.model_id === selected.value?.model_id)) {
    selectedId.value = null
    compareRows.value = []
  }
}

function canTrainRow(row: DriftItem): boolean {
  if (!canManage.value) return false
  return varietyIdByName.value.has(row.variety) && regionIdByName.value.has(row.region)
}

async function fetchDicts() {
  dicts.value = await api.get<MetaDicts>('/meta/dicts')
}

async function fetchDrift() {
  const data = await api.get<DriftData>('/models/drift', { window: windowDays.value })
  const list = data.items || []
  driftItems.value = list
  checkedAt.value = data.checked_at || ''
  if (data.summary) {
    summary.value = data.summary
  } else {
    summary.value = {
      total: list.length,
      stable: list.filter((item) => item.drift_level === '平稳').length,
      watch: list.filter((item) => item.drift_level === '关注').length,
      drifted: list.filter((item) => item.drift_level === '漂移').length,
      avg_psi: list.length
        ? list.reduce((sum, item) => sum + (Number(item.psi) || 0), 0) / list.length
        : 0,
    }
  }
  if (selectedId.value && !list.some((item) => item.model_id === selectedId.value)) {
    selectedId.value = null
    compareRows.value = []
  }
}

async function loadDrift() {
  loading.value = true
  try {
    await fetchDrift()
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    loading.value = false
  }
}

async function refreshAll() {
  loading.value = true
  try {
    const results = await Promise.allSettled([fetchDicts(), fetchDrift()])
    if (results.some((item) => item.status === 'rejected')) {
      ElMessage.warning('数据服务暂不可用')
    }
  } finally {
    loading.value = false
  }
}

async function fetchCompare(row: DriftItem) {
  const varietyId = varietyIdByName.value.get(row.variety)
  const regionId = regionIdByName.value.get(row.region)
  if (!varietyId || !regionId) {
    compareRows.value = []
    compareMissing.value = true
    return
  }
  compareMissing.value = false
  compareRows.value = await api.get<CompareRow[]>('/models/compare', {
    variety_id: varietyId,
    region_id: regionId,
  })
}

async function loadCompare(row: DriftItem) {
  compareLoading.value = true
  compareMissing.value = false
  try {
    await fetchCompare(row)
  } catch {
    compareRows.value = []
    ElMessage.warning('数据服务暂不可用')
  } finally {
    compareLoading.value = false
  }
}

function selectModel(row: DriftItem) {
  if (selectedId.value === row.model_id) return
  selectedId.value = row.model_id
  loadCompare(row)
}

function onRowClick(row: DriftItem) {
  selectModel(row)
}

async function retrain(row: DriftItem) {
  if (!canTrainRow(row)) return
  const varietyId = varietyIdByName.value.get(row.variety)
  const regionId = regionIdByName.value.get(row.region)
  if (!varietyId || !regionId) {
    ElMessage.warning('缺少品种或地区标识，无法重训')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认重训「${row.name}」？训练将基于最新数据，可能需要数秒。`,
      '重训确认',
      { type: 'warning', confirmButtonText: '开始重训', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  trainingId.value = row.model_id
  try {
    await api.post('/models/train', { variety_id: varietyId, region_id: regionId })
    ElMessage.success('模型重训完成')
    await fetchDrift()
    if (selectedId.value === row.model_id) await loadCompare(row)
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    trainingId.value = null
  }
}

onMounted(refreshAll)
</script>

<style scoped>
.drift-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(360px, 1fr);
  gap: 16px;
  align-items: start;
}

@media (max-width: 1180px) {
  .drift-layout {
    grid-template-columns: 1fr;
  }
}

.table-card {
  min-width: 0;
}

.compare-card {
  min-width: 0;
}

.selected-hint {
  font-size: 12px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  max-width: 240px;
}

.model-name {
  font-size: 13px;
  font-weight: 500;
  color: #1c2a3a;
}

.model-key {
  margin-top: 1px;
  font-size: 11px;
}

.compare-sub {
  font-size: 12px;
  font-weight: 400;
}

.psi-panel {
  padding: 12px 14px;
  border: 1px solid #e9eef7;
  border-radius: 8px;
  background: #f7f9fd;
}

.psi-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.psi-label {
  font-size: 13px;
  font-weight: 600;
  color: #40536b;
}

.psi-value-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}

.psi-value {
  font-size: 26px;
  font-weight: 700;
  color: #16233a;
  letter-spacing: 0.5px;
}

.psi-threshold {
  font-size: 11px;
}

.psi-rules {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 8px;
  font-size: 11px;
  color: #5b6b7f;
}

.psi-rules span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.dot-stable {
  background: #1c9c6b;
}

.dot-watch {
  background: #e6a23c;
}

.dot-drift {
  background: #d64545;
}

.psi-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin-top: 10px;
  padding-top: 9px;
  border-top: 1px dashed #dde5f1;
  font-size: 12px;
  color: #5b6b7f;
}

.psi-meta b {
  font-weight: 600;
  color: #1c2a3a;
}

.psi-tip {
  margin: 9px 0 0;
  font-size: 11px;
  line-height: 1.7;
  color: #8b9aae;
}

.compare-block {
  margin-top: 14px;
}

.compare-title {
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #40536b;
}

.compare-title .muted {
  font-size: 11px;
  font-weight: 400;
}

.drift-layout :deep(.selected-row) {
  background: #eef4ff !important;
}

.drift-layout :deep(.el-table__row) {
  cursor: pointer;
}
</style>
