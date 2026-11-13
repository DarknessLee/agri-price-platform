<template>
  <div class="page">
    <PageHeader title="模型管理" subtitle="查看预测模型表现，训练新版本并激活线上模型" />

    <div class="kpi-grid">
      <KpiCard label="模型总数" :value="models.length" icon="Files" tone="blue" hint="当前筛选条件下的模型" />
      <KpiCard label="生效模型" :value="activeCount" icon="CircleCheck" tone="green" hint="线上正在使用的模型" />
      <KpiCard label="平均 MAPE" :value="avgMapeText" unit="%" icon="DataLine" tone="orange" hint="数值越低预测越准确" />
      <KpiCard label="平均方向准确率" :value="avgAccText" unit="%" icon="TrendCharts" tone="purple" hint="涨跌方向判断准确率" />
    </div>

    <div v-if="canManage" class="page-card">
      <div class="card-title">
        <span>模型训练</span>
        <span class="muted panel-hint">基于最新历史价格数据重新拟合，训练耗时与数据量相关</span>
      </div>
      <div class="train-bar">
        <el-checkbox v-model="trainAll" :disabled="!canManage || training">训练全部品种</el-checkbox>
        <el-select
          v-model="trainVarietyId"
          clearable
          filterable
          placeholder="选择品种"
          :disabled="trainAll || !canManage || training"
          style="width: 190px"
        >
          <el-option
            v-for="item in dicts?.varieties || []"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>
        <el-tooltip :disabled="canManage" content="暂无模型管理权限，无法执行训练" placement="top">
          <span>
            <el-button
              type="primary"
              :loading="training"
              :disabled="!canManage || training || (!trainAll && !trainVarietyId)"
              @click="trainModels"
            >
              {{ training ? '训练中' : '开始训练' }}
            </el-button>
          </span>
        </el-tooltip>
        <span v-if="trainAll" class="muted train-tip">将训练全部品种与地区组合的模型，耗时较长</span>
        <span v-else-if="!trainVarietyId" class="muted train-tip">请选择品种，或勾选“训练全部品种”</span>
      </div>
      <div v-if="trainSummary" class="train-result">
        <div class="train-result-title">最近一次训练：{{ trainSummary.name }}（版本 {{ trainSummary.version }}）</div>
        <div class="muted">
          MAPE {{ fmtNum(trainSummary.mape, 2) }}% · RMSE {{ fmtNum(trainSummary.rmse, 2) }} · 方向准确率
          {{ fmtNum(trainSummary.direction_acc, 1) }}% · 样本 {{ fmtInt(trainSummary.rows) }} 条
        </div>
      </div>
    </div>

    <div class="page-card">
      <div class="flex-between list-head">
        <div class="card-title list-title"><span>模型列表</span></div>
        <div class="toolbar list-toolbar">
          <el-select
            v-model="filterVariety"
            clearable
            filterable
            placeholder="按品种筛选"
            style="width: 170px"
            @change="loadModels"
          >
            <el-option
              v-for="item in dicts?.varieties || []"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
          <el-button :loading="listLoading" @click="loadModels">刷新</el-button>
        </div>
      </div>

      <el-table :data="models" size="small" stripe max-height="560" v-loading="listLoading">
        <el-table-column label="模型名称" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="model-name">{{ row.name }}</div>
            <div class="muted model-key mono">{{ row.key }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="variety" label="品种" min-width="88" show-overflow-tooltip />
        <el-table-column prop="region" label="地区" min-width="92" show-overflow-tooltip />
        <el-table-column prop="algorithm" label="算法" min-width="114" show-overflow-tooltip />
        <el-table-column prop="version" label="版本" width="76" align="center" />
        <el-table-column label="MAPE" width="88" align="right">
          <template #default="{ row }">{{ fmtNum(row.mape, 2) }}%</template>
        </el-table-column>
        <el-table-column label="方向准确率" width="104" align="right">
          <template #default="{ row }">{{ fmtNum(row.direction_acc, 1) }}%</template>
        </el-table-column>
        <el-table-column label="样本量" width="92" align="right">
          <template #default="{ row }">{{ fmtInt(row.rows) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="92" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_active" type="success" size="small" effect="plain">生效中</el-tag>
            <el-tag v-else type="info" size="small" effect="plain">候选</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="训练时间" min-width="148">
          <template #default="{ row }">{{ fmtDateTime(row.trained_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="132" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openBacktest(row)">回测</el-button>
            <el-tooltip :disabled="canManage || row.is_active" content="暂无模型管理权限" placement="top">
              <span class="activate-wrap">
                <el-button
                  link
                  type="primary"
                  size="small"
                  :disabled="row.is_active || !canManage"
                  :loading="activatingId === row.id"
                  @click="activateModel(row)"
                >
                  {{ row.is_active ? '已激活' : '激活' }}
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无模型数据，可先执行一次模型训练" :image-size="64" />
        </template>
      </el-table>
    </div>

    <div class="page-card">
      <div class="flex-between list-head">
        <div class="card-title list-title">
          <span>训练实验记录</span>
        </div>
        <div class="toolbar list-toolbar">
          <el-select
            v-model="runVarietyId"
            clearable
            filterable
            placeholder="按品种筛选"
            style="width: 150px"
            @change="loadRuns"
          >
            <el-option
              v-for="item in dicts?.varieties || []"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
          <el-select
            v-model="runRegionId"
            clearable
            filterable
            placeholder="按地区筛选"
            style="width: 150px"
            @change="loadRuns"
          >
            <el-option
              v-for="item in dicts?.regions || []"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
          <span class="muted">最近 {{ fmtInt(runList.length) }} 条 · 最多 50 条</span>
          <el-button :loading="runsLoading" @click="loadRuns">刷新</el-button>
        </div>
      </div>

      <el-table v-loading="runsLoading" :data="runList" size="small" stripe max-height="420">
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="模型" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="model-name">{{ row.name || row.key || '—' }}</div>
            <div class="muted model-key mono">{{ row.key }}</div>
          </template>
        </el-table-column>
        <el-table-column label="算法" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ algorithmText(row.algorithm) }}</template>
        </el-table-column>
        <el-table-column label="品种" width="90" show-overflow-tooltip>
          <template #default="{ row }">{{ row.variety || '—' }}</template>
        </el-table-column>
        <el-table-column label="地区" width="96" show-overflow-tooltip>
          <template #default="{ row }">{{ row.region || '—' }}</template>
        </el-table-column>
        <el-table-column label="触发方式" width="96" align="center">
          <template #default="{ row }">{{ triggerLabel(row.trigger) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="88" align="center">
          <template #default="{ row }">
            <el-tag :type="runStatusTag(row.status)" size="small" effect="plain">
              {{ row.status || '—' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="88" align="right">
          <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="MAPE" width="82" align="right">
          <template #default="{ row }">{{ metricOf(row, 'mape', 2, '%') }}</template>
        </el-table-column>
        <el-table-column label="方向准确率" width="100" align="right">
          <template #default="{ row }">{{ metricOf(row, 'direction_acc', 1, '%') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="76" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openRunDetail(row)">详情</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无训练实验记录，完成一次模型训练后自动写入" :image-size="64" />
        </template>
      </el-table>
    </div>

    <el-drawer v-model="runDetailVisible" title="训练实验详情" size="520px" destroy-on-close>
      <div v-if="runDetail" class="run-detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="模型">
            {{ runDetail.name || '—' }}<span class="muted mono">（{{ runDetail.key }}）</span>
          </el-descriptions-item>
          <el-descriptions-item label="算法">{{ algorithmText(runDetail.algorithm) }}</el-descriptions-item>
          <el-descriptions-item label="品种 / 地区">
            {{ runDetail.variety || '—' }} · {{ runDetail.region || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="版本">{{ runDetail.version || '—' }}</el-descriptions-item>
          <el-descriptions-item label="触发方式">{{ triggerLabel(runDetail.trigger) }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="runStatusTag(runDetail.status)" size="small" effect="plain">
              {{ runDetail.status || '—' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="耗时">{{ formatDuration(runDetail.duration_ms) }}</el-descriptions-item>
          <el-descriptions-item label="样本量">{{ fmtInt(runDetail.rows) }}</el-descriptions-item>
          <el-descriptions-item label="操作人">{{ runDetail.operator || '—' }}</el-descriptions-item>
          <el-descriptions-item label="时间">{{ fmtDateTime(runDetail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="产物键">
            <span class="mono">{{ runDetail.artifact_key || '—' }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <div class="dialog-section">
          <div class="section-title">指标（metrics）</div>
          <pre class="run-json mono">{{ jsonText(runDetail.metrics) }}</pre>
        </div>
        <div class="dialog-section">
          <div class="section-title">参数（params）</div>
          <pre class="run-json mono">{{ jsonText(runDetail.params) }}</pre>
        </div>
      </div>
      <el-empty v-else description="实验记录不存在" :image-size="72" />
    </el-drawer>

    <el-dialog v-model="backtestVisible" :title="backtestTitle" width="880px" top="6vh" destroy-on-close>
      <div v-loading="backtestLoading" class="backtest-body">
        <template v-if="backtest">
          <div class="metric-grid">
            <div class="metric-item">
              <span class="metric-label">MAPE</span>
              <span class="metric-value">{{ fmtNum(backtest.metrics.mape, 2) }}<em>%</em></span>
            </div>
            <div class="metric-item">
              <span class="metric-label">RMSE</span>
              <span class="metric-value">{{ fmtNum(backtest.metrics.rmse, 2) }}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">MAE</span>
              <span class="metric-value">{{ fmtNum(backtest.metrics.mae, 2) }}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">方向准确率</span>
              <span class="metric-value">{{ fmtNum(backtest.metrics.direction_acc, 1) }}<em>%</em></span>
            </div>
          </div>
          <div class="dialog-section">
            <div class="section-title">实际值与预测值对比（近 {{ backtest.window }} 天）</div>
            <BaseChart
              :option="backtestOption"
              :height="300"
              :empty="!backtest.points || backtest.points.length === 0"
              empty-text="暂无回测数据"
            />
          </div>
          <div class="dialog-section">
            <div class="section-title">特征重要性</div>
            <BaseChart
              :option="featureOption"
              :height="240"
              :empty="!backtest.feature_importance || backtest.feature_importance.length === 0"
              empty-text="暂无特征重要性数据"
            />
          </div>
        </template>
        <el-empty v-else-if="!backtestLoading" description="暂无回测数据" :image-size="72" />
      </div>
      <template #footer>
        <el-button @click="backtestVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { EChartsOption } from 'echarts'
import PageHeader from '@/components/PageHeader.vue'
import KpiCard from '@/components/KpiCard.vue'
import BaseChart from '@/components/BaseChart.vue'
import api from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { fmtDateTime, fmtInt, fmtNum } from '@/utils/format'
import type { MetaDicts } from '@/types'

interface ModelRow {
  id: number
  key: string
  name: string
  algorithm: string
  variety_id?: number
  variety: string
  region_id?: number
  region: string
  granularity?: string
  status: string
  is_active: boolean
  version: string
  mape: number
  rmse: number
  direction_acc: number
  rows: number
  trained_at: string
}

interface BacktestPoint {
  date: string
  actual: number
  predicted: number
  lower: number
  upper: number
}

interface BacktestData {
  window: number
  points: BacktestPoint[]
  metrics: { mape: number; rmse: number; mae: number; direction_acc: number }
  feature_importance: Array<{ factor: string; value: number }>
}

interface TrainedModel {
  id: number
  key: string
  name: string
  version: string
  mape: number
  rmse: number
  direction_acc: number
  rows: number
  trained_at?: string
}

interface ModelRunMetrics {
  mape?: number
  rmse?: number
  direction_acc?: number
  rows?: number
}

interface ModelRun {
  id: number
  model_id?: number
  key: string
  name?: string
  algorithm?: string
  variety?: string
  region?: string
  version?: string
  trigger?: string
  status?: string
  params?: Record<string, unknown> | string | null
  metrics?: ModelRunMetrics | string | null
  rows?: number
  duration_ms?: number | null
  artifact_key?: string
  operator?: string
  created_at?: string
}

interface ModelRunResponse {
  list?: ModelRun[]
  total?: number
}

const auth = useAuthStore()
const canManage = computed(() => auth.hasPerm('model:manage'))

const dicts = ref<MetaDicts | null>(null)
const models = ref<ModelRow[]>([])
const listLoading = ref(false)
const filterVariety = ref<number | null>(null)

const trainAll = ref(false)
const trainVarietyId = ref<number | null>(null)
const training = ref(false)
const trainSummary = ref<TrainedModel | null>(null)

const backtestVisible = ref(false)
const backtestLoading = ref(false)
const backtestModel = ref<ModelRow | null>(null)
const backtest = ref<BacktestData | null>(null)
const activatingId = ref<number | null>(null)

const runList = ref<ModelRun[]>([])
const runsLoading = ref(false)
const runVarietyId = ref<number | null>(null)
const runRegionId = ref<number | null>(null)
const runDetailVisible = ref(false)
const runDetail = ref<ModelRun | null>(null)

const ALGORITHM_LABELS: Record<string, string> = {
  ensemble: '组合模型',
  gbr: '梯度提升',
  seasonal: '季节分解',
  holt_winters: 'Holt-Winters',
}

const TRIGGER_LABELS: Record<string, string> = {
  manual: '手动训练',
  scheduled: '定时重训',
  auto: '自动重训',
  drift: '漂移重训',
  retrain: '重训',
}

function algorithmText(algorithm?: string): string {
  if (!algorithm) return '—'
  return ALGORITHM_LABELS[algorithm] || algorithm
}

function triggerLabel(trigger?: string): string {
  if (!trigger) return '—'
  return TRIGGER_LABELS[trigger] || trigger
}

function runStatusTag(status?: string): 'success' | 'danger' | 'warning' | 'info' {
  if (!status) return 'info'
  if (['成功', '已完成', 'success', 'done'].includes(status)) return 'success'
  if (['失败', 'failed', 'error'].includes(status)) return 'danger'
  if (['训练中', '运行中', 'running', 'pending', '排队中'].includes(status)) return 'warning'
  return 'info'
}

function formatDuration(duration?: number | null): string {
  if (duration == null || !Number.isFinite(Number(duration))) return '—'
  const value = Number(duration)
  if (value < 1000) return `${fmtInt(value)} ms`
  return `${fmtNum(value / 1000, 2)} s`
}

function metricsObject(metrics: ModelRun['metrics']): Record<string, number> {
  if (!metrics) return {}
  if (typeof metrics === 'string') {
    try {
      return JSON.parse(metrics) as Record<string, number>
    } catch {
      return {}
    }
  }
  return metrics as Record<string, number>
}

function metricOf(row: ModelRun, key: string, digits: number, suffix = ''): string {
  const value = metricsObject(row.metrics)[key]
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return `${fmtNum(Number(value), digits)}${suffix}`
}

function jsonText(value: unknown): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2) ?? value
    } catch {
      return value
    }
  }
  try {
    return JSON.stringify(value, null, 2) ?? String(value)
  } catch {
    return '—'
  }
}

function openRunDetail(row: ModelRun) {
  runDetail.value = row
  runDetailVisible.value = true
}

const activeCount = computed(() => models.value.filter((item) => item.is_active).length)

const avgMapeText = computed(() => {
  const values = models.value.map((item) => Number(item.mape)).filter((value) => Number.isFinite(value))
  if (!values.length) return '—'
  return fmtNum(values.reduce((sum, value) => sum + value, 0) / values.length, 2)
})

const avgAccText = computed(() => {
  const values = models.value
    .map((item) => Number(item.direction_acc))
    .filter((value) => Number.isFinite(value))
  if (!values.length) return '—'
  return fmtNum(values.reduce((sum, value) => sum + value, 0) / values.length, 1)
})

const backtestTitle = computed(() => `模型回测 · ${backtestModel.value?.name || ''}`)

const backtestOption = computed<EChartsOption>(() => {
  const data = backtest.value
  if (!data || !data.points.length) return {}
  const dates = data.points.map((item) => item.date)
  const actual = data.points.map((item) => item.actual)
  const predicted = data.points.map((item) => item.predicted)
  const lower = data.points.map((item) => item.lower)
  const upperSpan = data.points.map((item) => Math.max(item.upper - item.lower, 0))
  return {
    color: ['#1f5fd6', '#d9822b'],
    grid: { left: 12, right: 20, top: 40, bottom: 8, containLabel: true },
    legend: { top: 0, right: 8, icon: 'roundRect', itemWidth: 14, itemHeight: 6 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', label: { backgroundColor: '#1f5fd6' } },
      formatter: (params: any) => {
        const list = Array.isArray(params) ? params : [params]
        const index: number = list[0]?.dataIndex ?? 0
        const point = data.points[index]
        if (!point) return ''
        return `<div style="font-weight:600;margin-bottom:4px">${point.date}</div>
          <div style="line-height:1.7">实际值：<b>${fmtNum(point.actual, 2)}</b></div>
          <div style="line-height:1.7">预测值：<b>${fmtNum(point.predicted, 2)}</b></div>
          <div style="line-height:1.7">置信区间：${fmtNum(point.lower, 2)} ~ ${fmtNum(point.upper, 2)}</div>`
      },
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#e4e9f2' } },
      axisLabel: { color: '#7b8ba1', hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#7b8ba1' },
      splitLine: { lineStyle: { color: '#eef2f8', type: 'dashed' } },
    },
    series: [
      {
        name: '实际值',
        type: 'line',
        data: actual,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color: '#1f5fd6' },
        itemStyle: { color: '#1f5fd6' },
        z: 4,
      },
      {
        name: '预测值',
        type: 'line',
        data: predicted,
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { width: 2, color: '#d9822b', type: 'dashed' },
        itemStyle: { color: '#d9822b' },
        z: 5,
      },
      {
        name: '区间下限',
        type: 'line',
        stack: 'backtest-band',
        data: lower,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: 'transparent' },
        silent: true,
        z: 1,
      },
      {
        name: '置信区间',
        type: 'line',
        stack: 'backtest-band',
        data: upperSpan,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: 'rgba(31, 95, 214, 0.14)' },
        silent: true,
        z: 2,
      },
    ],
  }
})

const featureOption = computed<EChartsOption>(() => {
  const items = [...(backtest.value?.feature_importance || [])].sort((a, b) => b.value - a.value)
  return {
    grid: { left: 8, right: 52, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const list = Array.isArray(params) ? params : [params]
        const index: number = list[0]?.dataIndex ?? 0
        const item = items[index]
        if (!item) return ''
        return `<div style="font-weight:600;margin-bottom:4px">${item.factor}</div><div>重要性：${fmtNum(
          item.value,
          2,
        )}%</div>`
      },
    },
    xAxis: {
      type: 'value',
      max: 100,
      axisLabel: { color: '#7b8ba1', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#eef2f8', type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: items.map((item) => item.factor),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#40536b' },
    },
    series: [
      {
        name: '特征重要性',
        type: 'bar',
        barWidth: 12,
        data: items.map((item) => ({ value: item.value, itemStyle: { color: '#1f5fd6', borderRadius: 6 } })),
        label: {
          show: true,
          position: 'right',
          color: '#5b6b7f',
          fontSize: 11,
          formatter: (params: any) => `${fmtNum(params.value, 1)}%`,
        },
      },
    ],
  }
})

async function loadRuns() {
  runsLoading.value = true
  try {
    const params: Record<string, unknown> = { limit: 50 }
    if (runVarietyId.value) params.variety_id = runVarietyId.value
    if (runRegionId.value) params.region_id = runRegionId.value
    const data = await api.get<ModelRunResponse>('/models/runs', params)
    runList.value = data?.list || []
  } catch {
    runList.value = []
    ElMessage.warning('数据服务暂不可用')
  } finally {
    runsLoading.value = false
  }
}

async function loadDicts() {
  dicts.value = await api.get<MetaDicts>('/meta/dicts')
}

async function loadModels() {
  listLoading.value = true
  try {
    const params: Record<string, unknown> = {}
    if (filterVariety.value) params.variety_id = filterVariety.value
    models.value = await api.get<ModelRow[]>('/models', params)
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    listLoading.value = false
  }
}

async function trainModels() {
  if (!canManage.value) return
  if (!trainAll.value && !trainVarietyId.value) {
    ElMessage.warning('请选择品种或勾选训练全部品种')
    return
  }
  training.value = true
  try {
    const payload: Record<string, unknown> = {}
    if (!trainAll.value && trainVarietyId.value) payload.variety_id = trainVarietyId.value
    const trained = await api.post<TrainedModel>('/models/train', payload)
    trainSummary.value = trained
    ElMessage.success(`训练完成：${trained.name}`)
    await Promise.all([loadModels(), loadRuns()])
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    training.value = false
  }
}

async function activateModel(row: ModelRow) {
  if (!canManage.value || row.is_active) return
  try {
    await ElMessageBox.confirm(`确认将模型「${row.name}」激活为线上版本？`, '激活确认', {
      type: 'warning',
      confirmButtonText: '确认激活',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  activatingId.value = row.id
  try {
    await api.post(`/models/${row.id}/activate`)
    ElMessage.success('模型已激活')
    await loadModels()
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    activatingId.value = null
  }
}

async function openBacktest(row: ModelRow) {
  backtestModel.value = row
  backtest.value = null
  backtestVisible.value = true
  backtestLoading.value = true
  try {
    backtest.value = await api.get<BacktestData>(`/models/${row.id}/backtest`, { window: 60 })
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    backtestLoading.value = false
  }
}

onMounted(async () => {
  const tasks = await Promise.allSettled([loadDicts(), loadModels(), loadRuns()])
  if (tasks.some((item) => item.status === 'rejected')) {
    ElMessage.warning('数据服务暂不可用')
  }
})
</script>

<style scoped>
.panel-hint {
  font-size: 12px;
  font-weight: 400;
}

.train-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
}

.train-tip {
  font-size: 12px;
}

.train-result {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 8px;
  background: #f2f7ff;
  border: 1px solid #dce8fb;
}

.train-result-title {
  margin-bottom: 4px;
  font-weight: 600;
  color: #1c2a3a;
}

.list-head {
  margin-bottom: 14px;
}

.list-title {
  margin: 0;
}

.list-toolbar {
  margin: 0;
}

.model-name {
  font-weight: 500;
  color: #1c2a3a;
}

.model-key {
  margin-top: 2px;
  font-size: 11px;
  color: #8b9aae;
}

.activate-wrap {
  display: inline-block;
  margin-left: 6px;
}

.backtest-body {
  min-height: 160px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric-item {
  padding: 12px 14px;
  border-radius: 8px;
  background: #f7f9fd;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.metric-label {
  font-size: 12px;
  color: #7b8ba1;
}

.metric-value {
  font-size: 22px;
  font-weight: 600;
  color: #16233a;
  font-variant-numeric: tabular-nums;
}

.metric-value em {
  margin-left: 2px;
  font-size: 12px;
  font-style: normal;
  color: #8b9aae;
}

.dialog-section {
  margin-top: 18px;
}

.section-title {
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #1c2a3a;
}

.run-detail {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.run-json {
  margin: 0;
  padding: 12px 14px;
  max-height: 260px;
  overflow: auto;
  border-radius: 8px;
  border: 1px solid #e9eef7;
  background: #f7f9fd;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
