<template>
  <div class="page dashboard-page">
    <PageHeader title="综合驾驶舱" :subtitle="updatedText">
      <template #actions>
        <el-button type="primary" :loading="refreshing" @click="refresh">
          <el-icon><Refresh /></el-icon>刷新数据
        </el-button>
      </template>
    </PageHeader>

    <div class="dash-kpis">
      <KpiCard
        label="品种数量"
        :value="fmtInt(kpi.variety_count)"
        unit="种"
        icon="Goods"
        tone="blue"
        hint="在采农产品品类"
      />
      <KpiCard
        label="区域数量"
        :value="fmtInt(kpi.region_count)"
        unit="个"
        icon="MapLocation"
        tone="green"
        hint="覆盖产区与销区"
      />
      <KpiCard
        label="市场数量"
        :value="fmtInt(kpi.market_count)"
        unit="家"
        icon="Shop"
        tone="purple"
        hint="监测市场点位"
      />
      <KpiCard
        label="数据记录"
        :value="fmtInt(kpi.record_count)"
        unit="条"
        icon="Tickets"
        tone="orange"
        hint="累计入库价格记录"
      />
      <KpiCard
        label="平均价格"
        :value="fmtNum(kpi.avg_price, 2)"
        unit="元/公斤"
        icon="Money"
        tone="blue"
        :hint="`同比 ${fmtPct(kpi.yoy_pct)} · 完整率 ${fmtPct(kpi.completeness, 1, false)}`"
      />
      <KpiCard
        label="未处置预警"
        :value="fmtInt(kpi.alert_open)"
        unit="条"
        icon="Warning"
        tone="red"
        :hint="`今日新增 ${fmtInt(kpi.alert_today)} 条 · 预测精度 ${fmtPct(kpi.direction_acc, 1, false)}`"
      />
    </div>

    <section class="page-card">
      <div class="card-title">
        <span>价格走势</span>
        <div class="card-tools">
          <el-select v-model="varietyId" size="small" placeholder="选择品种" class="w-140" @change="onVarietyChange">
            <el-option v-for="item in varieties" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
          <el-select v-model="regionId" size="small" placeholder="选择地区" class="w-130" clearable @change="loadTrend">
            <el-option v-for="item in regions" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
          <span class="unit-tip">单位：元/公斤</span>
        </div>
      </div>
      <div v-if="trend?.latest" class="trend-meta">
        <span>{{ fmtDate(trend.latest.date) }}</span>
        <span class="trend-price">{{ fmtNum(trend.latest.price, 2) }}<em>元/公斤</em></span>
        <span :class="latestClass">{{ trendArrow(trend.latest.yoy_pct) }} {{ fmtPct(trend.latest.yoy_pct) }} 同比</span>
        <span>较上期 {{ trendArrow(trend.latest.change) }} {{ fmtNum(trend.latest.change, 2) }} 元/公斤</span>
        <span class="grow" />
        <span>近 90 天日频价格序列</span>
      </div>
      <BaseChart :option="trendOption" :height="330" :loading="trendLoading" :empty="!trendSeriesCount" empty-text="暂无价格走势数据" />
    </section>

    <div class="chart-grid-2">
      <section class="page-card">
        <div class="card-title">
          <span>区域价格指数</span>
          <span class="unit-tip">单位：元/公斤</span>
        </div>
        <BaseChart
          :option="regionOption"
          :height="300"
          :loading="regionLoading"
          :empty="!regionRows.length"
          empty-text="暂无区域价格数据"
        />
      </section>

      <section class="page-card">
        <div class="card-title">
          <span>品类占比</span>
          <span class="unit-tip">按记录条数统计</span>
        </div>
        <BaseChart
          :option="shareOption"
          :height="300"
          :loading="shareLoading"
          :empty="!shareRows.length"
          empty-text="暂无品类数据"
        />
      </section>
    </div>

    <div class="chart-grid-2">
      <section class="page-card">
        <div class="card-title">
          <span>最新预警</span>
          <el-button text type="primary" size="small" @click="router.push('/alert/list')">查看全部</el-button>
        </div>
        <el-table :data="alertRows" size="small" stripe class="clickable-table" @row-click="goAlert">
          <el-table-column label="级别" width="58">
            <template #default="{ row }">
              <el-tag :type="levelTagType(row.level)" size="small" effect="light">{{ row.level }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="预警内容" min-width="150" show-overflow-tooltip>
            <template #default="{ row }">{{ row.title || '—' }}</template>
          </el-table-column>
          <el-table-column label="品种" width="76" show-overflow-tooltip>
            <template #default="{ row }">{{ row.variety || '—' }}</template>
          </el-table-column>
          <el-table-column label="地区" width="90" show-overflow-tooltip>
            <template #default="{ row }">{{ row.region || '—' }}</template>
          </el-table-column>
          <el-table-column label="日期" width="88">
            <template #default="{ row }">{{ fmtDate(row.alert_date) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="70">
            <template #default="{ row }">
              <el-tag :type="alertStatusType(row.status)" size="small" effect="plain">{{ row.status || '—' }}</el-tag>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无预警信息" :image-size="60" />
          </template>
        </el-table>
      </section>

      <section class="page-card">
        <div class="card-title">
          <span>最新预测摘要</span>
          <el-button text type="primary" size="small" @click="router.push('/forecast/short')">查看全部</el-button>
        </div>
        <el-table :data="forecastRows" size="small" stripe class="clickable-table" @row-click="goForecast">
          <el-table-column label="品种" width="80" show-overflow-tooltip>
            <template #default="{ row }">{{ row.variety || '—' }}</template>
          </el-table-column>
          <el-table-column label="地区" width="96" show-overflow-tooltip>
            <template #default="{ row }">{{ row.region || '—' }}</template>
          </el-table-column>
          <el-table-column label="预测价(元/公斤)" width="112" align="right">
            <template #default="{ row }">{{ fmtNum(row.point, 2) }}</template>
          </el-table-column>
          <el-table-column label="变化" width="92" align="right">
            <template #default="{ row }">
              <span :class="changeClass(row.change_pct)">
                {{ trendArrow(row.change_pct) }} {{ fmtPct(row.change_pct) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="方向" width="70" align="center">
            <template #default="{ row }">{{ row.direction || '—' }}</template>
          </el-table-column>
          <el-table-column label="置信度" width="76" align="right">
            <template #default="{ row }">{{ confidenceText(row.confidence) }}</template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无预测摘要" :image-size="60" />
          </template>
        </el-table>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import KpiCard from '@/components/KpiCard.vue'
import BaseChart from '@/components/BaseChart.vue'
import { alertStatusType, fmtDate, fmtDateTime, fmtInt, fmtNum, fmtPct, levelTagType, trendArrow } from '@/utils/format'
import type { DictOption, MetaDicts } from '@/types'

interface SummaryKpi {
  variety_count?: number
  region_count?: number
  market_count?: number
  record_count?: number
  avg_price?: number
  yoy_pct?: number
  alert_open?: number
  alert_today?: number
  avg_mape?: number
  direction_acc?: number
  completeness?: number
}

interface DashboardSummary {
  kpi?: SummaryKpi & Record<string, number | null | undefined>
  latest_price_date?: string
  last_forecast_at?: string
  updated_at?: string
}

interface TrendLatest {
  date?: string
  price?: number
  yoy_pct?: number
  change?: number
}

interface TrendResp {
  dates: string[]
  series: Array<{ name: string; values: number[] }>
  unit?: string
  latest?: TrendLatest
}

interface RegionHeatRow {
  region_code?: string
  region: string
  price: number
  yoy_pct?: number
  level?: string
}

interface CategoryShareRow {
  category: string
  value: number
  record_count?: number
}

interface AlertRow {
  id: number
  level: string
  title: string
  variety?: string
  region?: string
  alert_date?: string
  status?: string
}

interface ForecastBriefRow {
  variety_id?: number
  variety: string
  region?: string
  horizon?: number
  point?: number
  change_pct?: number
  direction?: string
  confidence?: number
  forecast_date?: string
}

const router = useRouter()
const palette = ['#1f5fd6', '#2f9e8f', '#d9822b', '#d64545', '#6f42c1', '#3a8ee6']

const summary = ref<DashboardSummary>()
const trend = ref<TrendResp | null>(null)
const regionRows = ref<RegionHeatRow[]>([])
const shareRows = ref<CategoryShareRow[]>([])
const alertRows = ref<AlertRow[]>([])
const forecastRows = ref<ForecastBriefRow[]>([])

const varieties = ref<DictOption[]>([])
const regions = ref<DictOption[]>([])
const varietyId = ref<number | null>(null)
const regionId = ref<number | null>(null)

const refreshing = ref(false)
const summaryLoading = ref(false)
const trendLoading = ref(false)
const regionLoading = ref(false)
const shareLoading = ref(false)

let warned = false
function warnUnavailable() {
  if (warned) return
  warned = true
  ElMessage.warning('数据服务暂不可用')
}

const kpi = computed<Record<string, number | null | undefined>>(() => (summary.value?.kpi as Record<string, number>) || {})
const trendSeriesCount = computed(() => (trend.value?.series || []).filter((item) => item.values && item.values.length).length)

const updatedText = computed(() => {
  const parts: string[] = []
  parts.push(summary.value?.latest_price_date ? `数据更新至 ${fmtDate(summary.value.latest_price_date)}` : '数据更新至 —')
  if (summary.value?.last_forecast_at) parts.push(`最近预测 ${fmtDateTime(summary.value.last_forecast_at)}`)
  if (summary.value?.updated_at) parts.push(`汇总时间 ${fmtDateTime(summary.value.updated_at)}`)
  return parts.join(' · ')
})

const latestClass = computed(() => {
  const yoy = trend.value?.latest?.yoy_pct
  if (yoy === null || yoy === undefined || yoy === 0) return ''
  return yoy > 0 ? 'text-up' : 'text-down'
})

function changeClass(value?: number | null) {
  if (value === null || value === undefined || value === 0) return ''
  return value > 0 ? 'text-up' : 'text-down'
}

function confidenceText(value?: number | null) {
  if (value === null || value === undefined) return '—'
  return value <= 1 ? fmtPct(value * 100, 0, false) : fmtPct(value, 0, false)
}

function axisInterval(count: number): number | 'auto' {
  if (count <= 300) return 'auto'
  return Math.ceil(count / 12)
}

const trendOption = computed<any>(() => {
  const data = trend.value
  const dates = data?.dates || []
  const unit = data?.unit || '元/公斤'
  const series = (data?.series || []).map((item, index) => ({
    name: item.name || `序列${index + 1}`,
    type: 'line',
    smooth: true,
    showSymbol: dates.length <= 45,
    symbolSize: 5,
    data: item.values || [],
    lineStyle: { width: 2 },
    areaStyle:
      index === 0
        ? {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(31, 95, 214, 0.20)' },
                { offset: 1, color: 'rgba(31, 95, 214, 0.01)' },
              ],
            },
          }
        : undefined,
  }))
  return {
    color: palette,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: '#b9c7dd' } },
      valueFormatter: (value: unknown) => (value === null || value === undefined ? '—' : `${fmtNum(Number(value), 2)} ${unit}`),
    },
    legend: {
      top: 0,
      right: 0,
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      textStyle: { color: '#5b6b7f', fontSize: 12 },
    },
    grid: { left: 8, right: 16, top: 40, bottom: 6, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
      axisLine: { lineStyle: { color: '#e4e9f2' } },
      axisTick: { show: false },
      axisLabel: { color: '#7b8ba1', fontSize: 11, interval: axisInterval(dates.length) },
    },
    yAxis: {
      type: 'value',
      scale: true,
      splitLine: { lineStyle: { color: '#f0f3f9' } },
      axisLabel: { color: '#7b8ba1', fontSize: 11, formatter: (value: number) => fmtNum(value, 0) },
    },
    series,
  }
})

const regionOption = computed<any>(() => {
  const rows = [...regionRows.value].sort((a, b) => (a.price || 0) - (b.price || 0))
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : [params]
        const item = list[0] as { name?: string } | undefined
        const row = rows.find((entry) => entry.region === item?.name)
        if (!row) return ''
        return [
          `<div style="font-weight:600;margin-bottom:4px">${row.region}</div>`,
          `价格：${fmtNum(row.price, 2)} 元/公斤`,
          `同比：${fmtPct(row.yoy_pct)}`,
        ].join('<br/>')
      },
    },
    grid: { left: 8, right: 42, top: 10, bottom: 6, containLabel: true },
    xAxis: {
      type: 'value',
      scale: true,
      splitLine: { lineStyle: { color: '#f0f3f9' } },
      axisLabel: { color: '#7b8ba1', fontSize: 11, formatter: (value: number) => fmtNum(value, 0) },
    },
    yAxis: {
      type: 'category',
      data: rows.map((row) => row.region),
      axisLine: { lineStyle: { color: '#e4e9f2' } },
      axisTick: { show: false },
      axisLabel: { color: '#5b6b7f', fontSize: 12 },
    },
    series: [
      {
        type: 'bar',
        barMaxWidth: 18,
        label: { show: true, position: 'right', color: '#5b6b7f', fontSize: 11, formatter: (params: any) => fmtNum(params.value, 2) },
        data: rows.map((row) => ({
          value: row.price,
          itemStyle: {
            borderRadius: [0, 4, 4, 0],
            color: row.yoy_pct != null && row.yoy_pct > 0 ? '#d64545' : row.yoy_pct != null && row.yoy_pct < 0 ? '#2f9e8f' : '#1f5fd6',
          },
        })),
      },
    ],
  }
})

const shareOption = computed<any>(() => ({
  color: palette,
  tooltip: {
    trigger: 'item',
    formatter: (params: any) => `${params.name}<br/>记录数：${fmtInt(params.value)} 条（${params.percent}%）`,
  },
  legend: {
    orient: 'vertical',
    right: 6,
    top: 'center',
    icon: 'circle',
    itemWidth: 8,
    itemHeight: 8,
    textStyle: { color: '#5b6b7f', fontSize: 12 },
  },
  series: [
    {
      type: 'pie',
      radius: ['46%', '70%'],
      center: ['36%', '52%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
      label: { show: false },
      emphasis: { scale: true, label: { show: true, fontWeight: 600, formatter: '{b}\n{d}%' } },
      data: shareRows.value.map((row) => ({
        name: row.category,
        value: row.record_count ?? row.value,
      })),
    },
  ],
}))

async function loadMeta() {
  try {
    const data = await api.get<MetaDicts>('/meta/dicts')
    varieties.value = Array.isArray(data?.varieties) ? data.varieties : []
    regions.value = Array.isArray(data?.regions) ? data.regions : []
    if (varietyId.value === null) varietyId.value = varieties.value[0]?.id ?? null
    if (regionId.value === null) regionId.value = regions.value[0]?.id ?? null
  } catch {
    warnUnavailable()
    varieties.value = []
    regions.value = []
  }
}

async function loadSummary() {
  summaryLoading.value = true
  try {
    summary.value = await api.get<DashboardSummary>('/dashboard/summary')
  } catch {
    warnUnavailable()
    summary.value = undefined
  } finally {
    summaryLoading.value = false
  }
}

async function loadTrend() {
  if (varietyId.value === null) {
    trend.value = null
    return
  }
  trendLoading.value = true
  try {
    trend.value = await api.get<TrendResp>('/dashboard/trend', {
      variety_id: varietyId.value,
      region_id: regionId.value ?? undefined,
      days: 90,
    })
  } catch {
    warnUnavailable()
    trend.value = null
  } finally {
    trendLoading.value = false
  }
}

async function loadRegionHeat() {
  if (varietyId.value === null) {
    regionRows.value = []
    return
  }
  regionLoading.value = true
  try {
    const data = await api.get<RegionHeatRow[]>('/dashboard/region-heat', { variety_id: varietyId.value })
    regionRows.value = Array.isArray(data) ? data : []
  } catch {
    warnUnavailable()
    regionRows.value = []
  } finally {
    regionLoading.value = false
  }
}

async function loadShare() {
  shareLoading.value = true
  try {
    const data = await api.get<CategoryShareRow[]>('/dashboard/category-share')
    shareRows.value = Array.isArray(data) ? data : []
  } catch {
    warnUnavailable()
    shareRows.value = []
  } finally {
    shareLoading.value = false
  }
}

async function loadAlerts() {
  try {
    const data = await api.get<AlertRow[]>('/dashboard/alerts/latest', { limit: 6 })
    alertRows.value = Array.isArray(data) ? data : []
  } catch {
    warnUnavailable()
    alertRows.value = []
  }
}

async function loadForecastBrief() {
  try {
    const data = await api.get<ForecastBriefRow[]>('/dashboard/forecast-brief', { limit: 5 })
    forecastRows.value = Array.isArray(data) ? data : []
  } catch {
    warnUnavailable()
    forecastRows.value = []
  }
}

function onVarietyChange() {
  loadTrend()
  loadRegionHeat()
}

function goAlert() {
  router.push('/alert/list')
}

function goForecast() {
  router.push('/forecast/short')
}

async function loadAll() {
  await loadMeta()
  await Promise.all([loadSummary(), loadTrend(), loadRegionHeat(), loadShare(), loadAlerts(), loadForecastBrief()])
}

async function refresh() {
  refreshing.value = true
  await loadAll()
  refreshing.value = false
}

onMounted(loadAll)
</script>

<style scoped>
.dashboard-page {
  padding-bottom: 8px;
}

.dash-kpis {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 14px;
}

.card-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.w-140 {
  width: 140px;
}

.w-130 {
  width: 130px;
}

.unit-tip {
  font-size: 12px;
  color: #8b9aae;
  white-space: nowrap;
}

.trend-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 14px;
  margin: -6px 0 6px;
  font-size: 12px;
  color: #7b8ba1;
}

.trend-price {
  font-size: 20px;
  font-weight: 600;
  color: #16233a;
  font-variant-numeric: tabular-nums;
}

.trend-price em {
  font-style: normal;
  font-size: 12px;
  font-weight: 400;
  color: #8b9aae;
  margin-left: 4px;
}

.trend-meta .grow {
  flex: 1;
}

.clickable-table :deep(.el-table__row) {
  cursor: pointer;
}

@media (max-width: 1400px) {
  .dash-kpis {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .dash-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
