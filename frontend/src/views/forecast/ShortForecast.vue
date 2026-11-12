<template>
  <div class="page">
    <PageHeader title="短期预测" subtitle="基于历史价格与季节特征，生成未来价格走势及置信区间">
      <template #actions>
        <el-button type="primary" :loading="running" :disabled="running || !canRun" @click="runForecast">
          {{ running ? '预测计算中' : '开始预测' }}
        </el-button>
      </template>
    </PageHeader>

    <div class="page-card">
      <div class="card-title">
        <span>预测条件</span>
        <span class="muted condition-hint">单次预测通常需要几秒，请耐心等待</span>
      </div>
      <el-form :model="form" label-width="84px" class="condition-form">
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :lg="6">
            <el-form-item label="品种">
              <el-select v-model="form.variety_id" filterable placeholder="请选择品种" style="width: 100%">
                <el-option
                  v-for="item in dicts?.varieties || []"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="6">
            <el-form-item label="地区">
              <el-select v-model="form.region_id" filterable placeholder="请选择地区" style="width: 100%">
                <el-option
                  v-for="item in dicts?.regions || []"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="24" :lg="12">
            <el-form-item label="预测天数">
              <el-radio-group v-model="horizonPreset">
                <el-radio-button :value="7">7 天</el-radio-button>
                <el-radio-button :value="14">14 天</el-radio-button>
                <el-radio-button :value="30">30 天</el-radio-button>
                <el-radio-button value="custom">自定义</el-radio-button>
              </el-radio-group>
              <el-input-number
                v-if="horizonPreset === 'custom'"
                v-model="customHorizon"
                :min="1"
                :max="90"
                :step="1"
                controls-position="right"
                style="width: 116px; margin-left: 10px"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <div class="muted condition-tip">
        预测结果由模型测算得出，受市场波动影响仅供参考；预测区间越窄，代表模型对该区间的把握越高。
      </div>
    </div>

    <template v-if="result">
      <div class="summary-card">
        <div class="summary-head">
          <div>
            <div class="summary-caption">{{ result.model.name }} · 未来 {{ result.forecast.length }} 天</div>
            <div class="summary-change">
              {{ fmtPct(result.summary.expected_change_pct, 2) }}
              <span class="summary-arrow">{{ trendArrow(result.summary.expected_change_pct) }}</span>
            </div>
            <div class="summary-sub">预计变动幅度（截至 {{ lastForecastDate }}）</div>
          </div>
          <div class="summary-tags">
            <el-tag :type="directionTagType(result.summary.trend)" effect="dark" round>
              {{ directionLabel(result.summary.trend) }}
            </el-tag>
            <el-tag :type="riskTagType(result.summary.risk_level)" effect="dark" round>
              风险等级 {{ result.summary.risk_level }}
            </el-tag>
            <el-tag type="info" effect="dark" round>
              置信度 {{ result.summary.confidence_level }}
            </el-tag>
          </div>
        </div>
        <div class="summary-text">{{ result.summary.text }}</div>
        <div class="summary-meta">
          <span>模型 {{ result.model.name }}</span>
          <span>MAPE {{ fmtNum(result.model.mape, 2) }}%</span>
          <span>方向准确率 {{ fmtNum(result.model.direction_acc, 1) }}%</span>
          <span>生成时间 {{ fmtDateTime(result.created_at) }}</span>
        </div>
      </div>

      <div class="page-card">
        <div class="card-title">
          <span>价格走势与置信区间</span>
          <span class="muted condition-hint">
            {{ result.history.dates[0] || '—' }} 至 {{ lastForecastDate }}
          </span>
        </div>
        <BaseChart :option="trendOption" :height="380" :loading="running" />
      </div>

      <div class="chart-grid-2">
        <div class="page-card">
          <div class="card-title">
            <span>预测明细</span>
            <span class="muted condition-hint">共 {{ result.forecast.length }} 天</span>
          </div>
          <el-table :data="result.forecast" size="small" stripe max-height="336">
            <el-table-column prop="target_date" label="日期" min-width="108" />
            <el-table-column label="预测价格" min-width="96" align="right">
              <template #default="{ row }">{{ fmtNum(row.point, 2) }}</template>
            </el-table-column>
            <el-table-column label="置信区间" min-width="150" align="right">
              <template #default="{ row }">{{ fmtNum(row.lower, 2) }} ~ {{ fmtNum(row.upper, 2) }}</template>
            </el-table-column>
            <el-table-column label="置信度" width="86" align="right">
              <template #default="{ row }">{{ confidenceText(row.confidence) }}</template>
            </el-table-column>
            <el-table-column label="方向" width="82" align="center">
              <template #default="{ row }">
                <el-tag :type="directionTagType(row.direction)" size="small" effect="plain">
                  {{ directionLabel(row.direction) }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="page-card">
          <div class="card-title">
            <span>因素贡献</span>
            <span class="muted condition-hint">影响本次预测的主要因素</span>
          </div>
          <BaseChart
            :option="explainOption"
            :height="300"
            :empty="!result.explain || result.explain.length === 0"
            empty-text="暂无因素贡献数据"
          />
          <div v-if="result.explain && result.explain.length" class="explain-notes">
            <div v-for="item in result.explain.slice(0, 3)" :key="item.factor" class="explain-note">
              <span class="explain-factor">{{ item.factor }}</span>
              <span class="muted">{{ item.description }}</span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="page-card">
      <el-empty description="选择品种和地区后，点击“开始预测”查看结果" :image-size="96" />
    </div>

    <div class="chart-grid-2">
      <div class="page-card">
        <div class="card-title">
          <span>最近预测记录</span>
          <span class="muted condition-hint">点击记录可回看详情</span>
        </div>
        <el-table
          :data="recent"
          size="small"
          max-height="280"
          highlight-current-row
          class="clickable-table"
          @row-click="openResult"
        >
          <el-table-column prop="variety" label="品种" min-width="86" show-overflow-tooltip />
          <el-table-column prop="region" label="地区" min-width="90" show-overflow-tooltip />
          <el-table-column label="天数" width="68" align="center">
            <template #default="{ row }">{{ row.horizon }} 天</template>
          </el-table-column>
          <el-table-column label="MAPE" width="86" align="right">
            <template #default="{ row }">{{ fmtNum(row.mape, 2) }}%</template>
          </el-table-column>
          <el-table-column label="预计变动" width="96" align="right">
            <template #default="{ row }">
              <span :class="changeClass(row.expected_change_pct)">{{ fmtPct(row.expected_change_pct, 2) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="生成时间" min-width="132">
            <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无预测记录" :image-size="60" />
          </template>
        </el-table>
      </div>

      <div class="page-card">
        <div class="card-title">
          <span>模型表现概览</span>
          <span class="muted condition-hint">近 30 天滚动评估</span>
        </div>
        <div class="perf-row">
          <div class="perf-item">
            <span class="perf-label">平均 MAPE</span>
            <span class="perf-value">{{ fmtNum(performance?.avg_mape, 2) }}%</span>
          </div>
          <div class="perf-item">
            <span class="perf-label">平均方向准确率</span>
            <span class="perf-value">{{ fmtNum(performance?.avg_direction_acc, 1) }}%</span>
          </div>
          <div class="perf-item">
            <span class="perf-label">覆盖品种</span>
            <span class="perf-value">{{ fmtInt(performance?.by_variety?.length) }}</span>
          </div>
        </div>
        <el-table :data="performance?.by_variety || []" size="small" max-height="220">
          <el-table-column prop="variety" label="品种" min-width="96" show-overflow-tooltip />
          <el-table-column label="MAPE" width="96" align="right">
            <template #default="{ row }">{{ fmtNum(row.mape, 2) }}%</template>
          </el-table-column>
          <el-table-column label="方向准确率" width="112" align="right">
            <template #default="{ row }">{{ fmtNum(row.direction_acc, 1) }}%</template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无评估数据" :image-size="60" />
          </template>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { EChartsOption } from 'echarts'
import PageHeader from '@/components/PageHeader.vue'
import BaseChart from '@/components/BaseChart.vue'
import api from '@/api/client'
import {
  fmtDateTime,
  fmtInt,
  fmtNum,
  fmtPct,
  trendArrow,
} from '@/utils/format'
import type { ForecastPoint, ForecastRunResult, MetaDicts } from '@/types'

interface ForecastResultRow {
  id: number
  variety: string
  region: string
  horizon: number
  model?: string
  mape: number
  expected_change_pct: number
  direction?: string
  created_at: string
}

interface PerformanceData {
  avg_mape: number
  avg_direction_acc: number
  series: Array<{ date: string; mape: number; direction_acc: number }>
  by_variety: Array<{ variety: string; mape: number; direction_acc: number }>
}

type HorizonPreset = 7 | 14 | 30 | 'custom'

const dicts = ref<MetaDicts | null>(null)
const recent = ref<ForecastResultRow[]>([])
const performance = ref<PerformanceData | null>(null)
const result = ref<ForecastRunResult | null>(null)
const running = ref(false)
const detailLoading = ref(false)
const horizonPreset = ref<HorizonPreset>(14)
const customHorizon = ref(30)

const form = reactive<{ variety_id: number | null; region_id: number | null }>({
  variety_id: null,
  region_id: null,
})

const effectiveHorizon = computed(() => {
  const raw = horizonPreset.value === 'custom' ? customHorizon.value : horizonPreset.value
  const num = Number(raw)
  if (!Number.isFinite(num)) return 14
  return Math.min(90, Math.max(1, Math.round(num)))
})

const canRun = computed(() => Boolean(form.variety_id && form.region_id))

const unitLabel = computed(() => {
  const item = (dicts.value?.varieties || []).find((v) => v.id === form.variety_id)
  return item?.unit || '元/公斤'
})

const lastForecastDate = computed(() => {
  if (!result.value || !result.value.forecast.length) return '—'
  return result.value.forecast[result.value.forecast.length - 1].target_date
})

const trendOption = computed<EChartsOption>(() => {
  const res = result.value
  if (!res) return {}
  const historyDates = res.history.dates || []
  const values = res.history.values || []
  const forecasts = res.forecast || []
  const hLen = historyDates.length
  const dates = [...historyDates, ...forecasts.map((item) => item.target_date)]

  const actual: Array<number | null> = [...values, ...forecasts.map(() => null)]
  const forecastLine: Array<number | null> = [
    ...Array.from({ length: hLen }, () => null),
    ...forecasts.map((item) => item.point),
  ]
  if (hLen > 0) forecastLine[hLen - 1] = values[hLen - 1]

  const lowerBand: Array<number | null> = [
    ...Array.from({ length: hLen }, () => null),
    ...forecasts.map((item) => item.lower),
  ]
  const upperSpan: Array<number | null> = [
    ...Array.from({ length: hLen }, () => null),
    ...forecasts.map((item) => Math.max(item.upper - item.lower, 0)),
  ]

  return {
    color: ['#1f5fd6', '#d9822b'],
    grid: { left: 12, right: 20, top: 44, bottom: 8, containLabel: true },
    legend: { top: 0, right: 8, icon: 'roundRect', itemWidth: 14, itemHeight: 6 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', label: { backgroundColor: '#1f5fd6' } },
      formatter: (params: any) => {
        const list = Array.isArray(params) ? params : [params]
        const index: number = list[0]?.dataIndex ?? 0
        const date = dates[index] || ''
        const rows: string[] = []
        if (index < hLen) {
          rows.push(`实际价格：<b>${fmtNum(values[index], 2)}</b> ${unitLabel.value}`)
        } else {
          const point: ForecastPoint | undefined = forecasts[index - hLen]
          if (point) {
            rows.push(`预测价格：<b>${fmtNum(point.point, 2)}</b> ${unitLabel.value}`)
            rows.push(`置信区间：${fmtNum(point.lower, 2)} ~ ${fmtNum(point.upper, 2)}`)
            rows.push(`方向：${directionLabel(point.direction)}`)
            rows.push(`置信度：${confidenceText(point.confidence)}`)
          }
        }
        return `<div style="font-weight:600;margin-bottom:4px">${date}</div>${rows
          .map((row) => `<div style="line-height:1.7">${row}</div>`)
          .join('')}`
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
      name: unitLabel.value,
      nameTextStyle: { color: '#7b8ba1', padding: [0, 0, 6, 0] },
      axisLabel: { color: '#7b8ba1' },
      splitLine: { lineStyle: { color: '#eef2f8', type: 'dashed' } },
    },
    series: [
      {
        name: '历史价格',
        type: 'line',
        data: actual,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color: '#1f5fd6' },
        itemStyle: { color: '#1f5fd6' },
        z: 4,
      },
      {
        name: '预测价格',
        type: 'line',
        data: forecastLine,
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 2, color: '#d9822b', type: 'dashed' },
        itemStyle: { color: '#d9822b' },
        z: 5,
        markLine: hLen
          ? {
              symbol: 'none',
              silent: true,
              lineStyle: { color: '#98a6ba', type: 'dashed', width: 1 },
              label: {
                formatter: '历史 / 预测',
                position: 'insideEndTop',
                color: '#5b6b7f',
                fontSize: 11,
              },
              data: [{ xAxis: historyDates[hLen - 1] }],
            }
          : undefined,
      },
      {
        name: '区间下限',
        type: 'line',
        stack: 'confidence',
        data: lowerBand,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: 'transparent' },
        silent: true,
        z: 1,
      },
      {
        name: '置信区间',
        type: 'line',
        stack: 'confidence',
        data: upperSpan,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: 'rgba(31, 95, 214, 0.16)' },
        silent: true,
        z: 2,
      },
    ],
  }
})

const explainOption = computed<EChartsOption>(() => {
  const items = [...(result.value?.explain || [])].sort(
    (a, b) => Math.abs(b.contribution) - Math.abs(a.contribution),
  )
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
        return `<div style="font-weight:600;margin-bottom:4px">${item.factor}</div><div>贡献度：${fmtNum(
          item.contribution,
          2,
        )}%</div><div style="max-width:260px;white-space:normal;color:#7b8ba1">${
          item.description || ''
        }</div>`
      },
    },
    xAxis: {
      type: 'value',
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
        name: '贡献度',
        type: 'bar',
        barWidth: 12,
        data: items.map((item) => ({
          value: item.contribution,
          itemStyle: { color: item.contribution >= 0 ? '#1f5fd6' : '#d64545', borderRadius: 6 },
        })),
        label: {
          show: true,
          position: 'right',
          color: '#5b6b7f',
          fontSize: 11,
          formatter: (params: any) => `${fmtNum(params.value, 2)}%`,
        },
      },
    ],
  }
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

function riskTagType(level?: string): 'danger' | 'warning' | 'info' {
  if (level === '高') return 'danger'
  if (level === '中') return 'warning'
  return 'info'
}

function changeClass(value?: number | null): string {
  if (value === null || value === undefined) return 'muted'
  if (value > 0) return 'text-up'
  if (value < 0) return 'text-down'
  return 'muted'
}

function confidenceText(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—'
  const num = Number(value)
  return `${(num <= 1 ? num * 100 : num).toFixed(0)}%`
}

async function loadDicts() {
  const data = await api.get<MetaDicts>('/meta/dicts')
  dicts.value = data
  if (!form.variety_id && data.varieties?.length) form.variety_id = data.varieties[0].id
  if (!form.region_id && data.regions?.length) form.region_id = data.regions[0].id
}

async function loadRecent() {
  recent.value = await api.get<ForecastResultRow[]>('/forecast/results', { limit: 20 })
}

async function loadPerformance() {
  performance.value = await api.get<PerformanceData>('/forecast/performance')
}

async function bootstrap() {
  const tasks = await Promise.allSettled([loadDicts(), loadRecent(), loadPerformance()])
  if (tasks.some((item) => item.status === 'rejected')) {
    ElMessage.warning('数据服务暂不可用')
  }
}

async function runForecast() {
  if (!form.variety_id || !form.region_id) {
    ElMessage.warning('请先选择品种和地区')
    return
  }
  running.value = true
  try {
    result.value = await api.post<ForecastRunResult>('/forecast/run', {
      variety_id: form.variety_id,
      region_id: form.region_id,
      horizon: effectiveHorizon.value,
      granularity: 'day',
    })
    ElMessage.success('预测完成')
    loadRecent().catch(() => {})
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    running.value = false
  }
}

async function openResult(row: ForecastResultRow) {
  detailLoading.value = true
  try {
    result.value = await api.get<ForecastRunResult>(`/forecast/result/${row.id}`)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    detailLoading.value = false
  }
}

onMounted(bootstrap)
</script>

<style scoped>
.condition-form {
  margin-bottom: 4px;
}

.condition-hint {
  font-size: 12px;
  font-weight: 400;
}

.condition-tip {
  font-size: 12px;
  line-height: 1.7;
}

.summary-card {
  padding: 20px 24px;
  border-radius: var(--ap-radius);
  background: linear-gradient(135deg, #16418f 0%, #1f5fd6 58%, #2f74ea 100%);
  color: #fff;
  box-shadow: 0 10px 24px rgba(31, 95, 214, 0.24);
}

.summary-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.summary-caption {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.76);
}

.summary-change {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 6px;
  font-size: 34px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}

.summary-arrow {
  font-size: 22px;
  opacity: 0.85;
}

.summary-sub {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.68);
}

.summary-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 4px;
}

.summary-text {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 8px;
  border-left: 3px solid rgba(255, 255, 255, 0.72);
  background: rgba(255, 255, 255, 0.13);
  font-size: 14px;
  line-height: 1.8;
}

.summary-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin-top: 14px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}

.explain-notes {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.explain-note {
  display: flex;
  gap: 8px;
  font-size: 12px;
  line-height: 1.6;
}

.explain-factor {
  flex-shrink: 0;
  color: #1f5fd6;
  font-weight: 500;
}

.clickable-table :deep(.el-table__row) {
  cursor: pointer;
}

.perf-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
}

.perf-item {
  flex: 1;
  min-width: 120px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f7f9fd;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.perf-label {
  font-size: 12px;
  color: #7b8ba1;
}

.perf-value {
  font-size: 20px;
  font-weight: 600;
  color: #16233a;
  font-variant-numeric: tabular-nums;
}
</style>
