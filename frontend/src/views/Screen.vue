<template>
  <div class="screen">
    <header class="screen-header">
      <div class="header-side left">
        <span class="live-dot" :class="{ off: offline }" />
        <span class="live-text">{{ offline ? '数据服务暂不可用' : '实时监测中' }}</span>
        <span v-if="loading" class="header-date">数据加载中…</span>
        <span v-else-if="latestDate" class="header-date">数据更新至 {{ latestDate }}</span>
      </div>
      <div class="header-center">
        <span class="deco-line" />
        <h1>农产品价格监测预测分析平台 · 数据大屏</h1>
        <span class="deco-line right" />
      </div>
      <div class="header-side right">
        <div class="clock">
          <span class="clock-date">{{ clockDate }}</span>
          <span class="clock-time">{{ clockTime }}</span>
        </div>
        <el-button class="refresh-btn" size="small" :loading="loading" title="刷新数据" @click="loadAll">
          <el-icon v-if="!loading"><Refresh /></el-icon>
        </el-button>
        <el-button class="back-btn" size="small" @click="router.push('/dashboard')">
          <el-icon><Back /></el-icon>
          <span>返回主界面</span>
        </el-button>
      </div>
    </header>

    <main class="screen-body">
      <section class="col col-left">
        <section class="panel rank-panel">
          <div class="panel-head">
            <h3>品种价格排行</h3>
            <span class="panel-sub">最新均价 · 元/公斤</span>
          </div>
          <div class="panel-body">
            <BaseChart
              :option="rankingOption"
              height="100%"
              :empty="!varietyRanking.length"
              empty-text="暂无品种价格数据"
            />
          </div>
        </section>
        <section class="panel share-panel">
          <div class="panel-head">
            <h3>品类占比</h3>
            <span class="panel-sub">按数据记录数</span>
          </div>
          <div class="panel-body">
            <BaseChart :option="shareOption" height="100%" :empty="!shareRows.length" empty-text="暂无品类数据" />
          </div>
        </section>
      </section>

      <section class="col col-center">
        <div class="kpi-grid">
          <div class="kpi-card tone-cyan">
            <div class="kpi-label">
              <el-icon><Money /></el-icon>
              平均价格
            </div>
            <div class="kpi-value">
              {{ kpi ? fmtNum(kpi.avg_price, 2) : '—' }}
              <em>元/公斤</em>
            </div>
            <div class="kpi-hint">{{ avgPriceHint }}</div>
          </div>
          <div class="kpi-card tone-blue">
            <div class="kpi-label">
              <el-icon><Tickets /></el-icon>
              数据记录
            </div>
            <div class="kpi-value">
              {{ kpi ? fmtInt(kpi.record_count) : '—' }}
              <em>条</em>
            </div>
            <div class="kpi-hint">{{ recordHint }}</div>
          </div>
          <div class="kpi-card tone-red">
            <div class="kpi-label">
              <el-icon><Warning /></el-icon>
              未处置预警
            </div>
            <div class="kpi-value">
              {{ kpi ? fmtInt(kpi.alert_open) : '—' }}
              <em>条</em>
            </div>
            <div class="kpi-hint">{{ alertHint }}</div>
          </div>
          <div class="kpi-card tone-amber">
            <div class="kpi-label">
              <el-icon><Aim /></el-icon>
              预测方向准确率
            </div>
            <div class="kpi-value">{{ kpi ? fmtPct(kpi.direction_acc, 1, false) : '—' }}</div>
            <div class="kpi-hint">{{ accuracyHint }}</div>
          </div>
        </div>

        <section class="panel trend-panel">
          <div class="panel-head">
            <h3>主力品种价格走势</h3>
            <span class="panel-sub">{{ trendSubtitle }}</span>
          </div>
          <div class="panel-body">
            <BaseChart
              :option="trendOption"
              height="100%"
              :empty="!trendDates.length"
              empty-text="暂无价格走势数据"
            />
          </div>
        </section>

        <section class="panel region-panel">
          <div class="panel-head">
            <h3>区域价格指数</h3>
            <span class="panel-sub">各地区均价 · 按同比着色</span>
          </div>
          <div class="panel-body">
            <BaseChart
              :option="regionOption"
              height="100%"
              :empty="!regionBars.length"
              empty-text="暂无区域价格数据"
            />
          </div>
        </section>
      </section>

      <section class="col col-right">
        <section class="panel alert-panel">
          <div class="panel-head">
            <h3>未处置预警</h3>
            <span class="panel-sub">{{ alertRows.length }} 条待处置</span>
          </div>
          <div class="panel-body">
            <div v-if="offline && !alertRows.length" class="panel-empty">数据服务暂不可用</div>
            <div v-else-if="!alertRows.length" class="panel-empty">暂无未处置预警</div>
            <div v-else class="alert-list">
              <div
                v-for="item in alertRows"
                :key="item.id"
                class="alert-item"
                @click="router.push('/alert/list')"
              >
                <span class="alert-level" :class="levelClass(item.level)">{{ item.level || '预警' }}</span>
                <div class="alert-main">
                  <div class="alert-title">{{ item.title }}</div>
                  <div class="alert-meta">
                    <span>{{ item.variety || '—' }}</span>
                    <span>{{ item.region || '—' }}</span>
                    <span>{{ fmtDate(item.alert_date) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="panel forecast-panel">
          <div class="panel-head">
            <h3>最新预测摘要</h3>
            <span class="panel-sub">点位 · 元/公斤</span>
          </div>
          <div class="panel-body">
            <div class="fc-table">
              <div class="fc-row fc-head">
                <span>品种</span>
                <span>地区</span>
                <span>预测价</span>
                <span>变化</span>
              </div>
              <template v-if="forecastRows.length">
                <div
                  v-for="item in forecastRows"
                  :key="`${item.variety}-${item.region || ''}-${item.forecast_date || ''}`"
                  class="fc-row"
                >
                  <span class="fc-name">{{ item.variety }}</span>
                  <span class="fc-muted">{{ item.region || '—' }}</span>
                  <span class="fc-price">{{ fmtNum(item.point, 2) }}</span>
                  <span :class="changeClass(item.change_pct)">{{ fmtPct(item.change_pct, 1) }}</span>
                </div>
              </template>
              <div v-else class="fc-empty">暂无预测数据</div>
              <div class="fc-foot">预测更新：{{ lastForecastText }}</div>
            </div>
          </div>
        </section>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import api, { type Paged } from '@/api/client'
import BaseChart from '@/components/BaseChart.vue'
import { fmtDate, fmtDateTime, fmtInt, fmtNum, fmtPct } from '@/utils/format'

interface DictOption {
  id: number
  code?: string
  name: string
  category?: string
  unit?: string
}

interface MetaDicts {
  varieties: DictOption[]
}

interface DashboardKpi {
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
  kpi?: DashboardKpi
  latest_price_date?: string
  last_forecast_at?: string
  updated_at?: string
}

interface TrendSeries {
  name: string
  values: Array<number | null>
}

interface TrendResp {
  dates: string[]
  series: TrendSeries[]
  unit?: string
  latest?: { date?: string; price?: number; yoy_pct?: number; change?: number }
}

interface RegionHeatRow {
  region_code?: string
  region: string
  price?: number | null
  yoy_pct?: number | null
  level?: string
}

interface CategoryShareRow {
  category?: string
  value?: number
  record_count?: number
  avg_price?: number
}

interface AlertRow {
  id: number
  level?: string
  title?: string
  variety?: string
  region?: string
  alert_date?: string
  status?: string
}

interface ForecastRow {
  variety_id?: number
  variety: string
  region?: string
  horizon?: number | string
  point?: number | null
  change_pct?: number | null
  direction?: string
  confidence?: number | null
  forecast_date?: string
}

type Settled<T> = { ok: true; data: T } | { ok: false }

async function safeGet<T>(promise: Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, data: await promise }
  } catch {
    return { ok: false }
  }
}

const router = useRouter()

const loading = ref(true)
const offline = ref(false)
const summary = ref<DashboardSummary | null>(null)
const trend = ref<TrendResp | null>(null)
const categoryShare = ref<CategoryShareRow[]>([])
const regionHeat = ref<RegionHeatRow[]>([])
const alerts = ref<AlertRow[]>([])
const forecasts = ref<ForecastRow[]>([])
const varieties = ref<DictOption[]>([])
const clock = ref(new Date())

let refreshTimer: number | undefined
let clockTimer: number | undefined
let refreshing = false

const kpi = computed(() => summary.value?.kpi || null)
const latestDate = computed(() => (summary.value?.latest_price_date ? fmtDate(summary.value.latest_price_date) : ''))
const lastForecastText = computed(() =>
  summary.value?.last_forecast_at ? fmtDateTime(summary.value.last_forecast_at) : '等待预测数据',
)

const clockDate = computed(() => {
  const date = clock.value
  const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][date.getDay()]
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day} ${week}`
})

const clockTime = computed(() => {
  const date = clock.value
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((value) => String(value).padStart(2, '0'))
    .join(':')
})

const avgPriceHint = computed(() =>
  kpi.value
    ? `同比 ${fmtPct(kpi.value.yoy_pct, 1)} · 完整率 ${fmtPct(kpi.value.completeness, 1, false)}`
    : '等待数据',
)

const recordHint = computed(() =>
  kpi.value
    ? `${fmtInt(kpi.value.variety_count)} 品种 · ${fmtInt(kpi.value.market_count)} 市场`
    : '等待数据',
)

const alertHint = computed(() =>
  kpi.value ? `今日新增 ${fmtInt(kpi.value.alert_today)} 条` : '等待数据',
)

const accuracyHint = computed(() =>
  kpi.value ? `MAPE ${fmtPct(kpi.value.avg_mape, 1, false)}` : '等待数据',
)

const trendDates = computed(() => trend.value?.dates || [])
const trendSeries = computed(() => trend.value?.series || [])
const compositeName = '综合均价'

const compositeSeries = computed(
  () => trendSeries.value.find((item) => item.name === compositeName) || null,
)

const varietyRanking = computed(() => {
  const rows = trendSeries.value
    .filter((item) => item.name && item.name !== compositeName)
    .map((item) => {
      let price: number | null = null
      for (let index = item.values.length - 1; index >= 0; index -= 1) {
        const value = item.values[index]
        if (typeof value === 'number' && Number.isFinite(value)) {
          price = value
          break
        }
      }
      return { name: item.name, price }
    })
  return rows
    .filter((item): item is { name: string; price: number } => item.price !== null)
    .sort((left, right) => right.price - left.price)
    .slice(0, 10)
})

const mainVarietyName = computed(() => varietyRanking.value[0]?.name || '')

const mainSeries = computed(
  () => trendSeries.value.find((item) => item.name === mainVarietyName.value) || null,
)

const trendSubtitle = computed(() => {
  const range = trendDates.value.length ? `近 ${trendDates.value.length} 个交易日` : '近 90 天'
  return mainVarietyName.value ? `${mainVarietyName.value} · ${range} · 元/公斤` : `${range} · 元/公斤`
})

const shareRows = computed(() =>
  (categoryShare.value || [])
    .map((item) => ({
      name: item.category || '其他',
      value: Number(item.record_count ?? item.value ?? 0),
    }))
    .filter((item) => Number.isFinite(item.value) && item.value > 0),
)

const regionBars = computed(() =>
  regionHeat.value
    .filter((item) => typeof item.price === 'number' && Number.isFinite(item.price))
    .sort((left, right) => (right.price as number) - (left.price as number))
    .slice(0, 12),
)

const alertRows = computed(() => alerts.value)
const forecastRows = computed(() => forecasts.value.slice(0, 5))

const rankColors = ['#f7b955', '#37d6f5', '#3d8bff', '#2f9e8f', '#5ad8a6', '#9b7bff', '#6aa8ff', '#4dd0c0', '#7ec8ff', '#2f6fbf']

const darkTooltip = {
  backgroundColor: 'rgba(6, 20, 38, 0.94)',
  borderColor: 'rgba(80, 160, 255, 0.35)',
  borderWidth: 1,
  textStyle: { color: '#dbe9ff', fontSize: 12 },
  extraCssText: 'box-shadow: 0 8px 24px rgba(0,0,0,0.4); border-radius: 8px;',
}

const rankingOption = computed<any>(() => {
  const rows = varietyRanking.value
  return {
    animationDuration: 900,
    grid: { left: 4, right: 58, top: 8, bottom: 4, containLabel: true },
    tooltip: {
      ...darkTooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(55, 214, 245, 0.06)' } },
      formatter: (params: any) => {
        const first = Array.isArray(params) ? params[0] : params
        return `${first.name}<br/><span style="color:#37d6f5;font-weight:600">${fmtNum(first.value, 2)}</span> 元/公斤`
      },
    },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#6f8fb8', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(96, 150, 220, 0.10)' } },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map((item) => item.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#b9d2f2', fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        barWidth: 9,
        data: rows.map((item, index) => ({
          value: item.price,
          itemStyle: {
            borderRadius: [0, 4, 4, 0],
            color: rankColors[index % rankColors.length],
            shadowColor: 'rgba(55, 214, 245, 0.35)',
            shadowBlur: 6,
          },
        })),
        label: {
          show: true,
          position: 'right',
          color: '#8fd6ff',
          fontSize: 10,
          formatter: (params: any) => fmtNum(params.value, 2),
        },
      },
    ],
  }
})

const shareOption = computed<any>(() => ({
  color: ['#37d6f5', '#3d8bff', '#f7b955', '#2f9e8f', '#ff6b6b', '#9b7bff', '#5ad8a6'],
  tooltip: {
    ...darkTooltip,
    trigger: 'item',
    formatter: (params: any) =>
      `${params.name}<br/><span style="color:#37d6f5;font-weight:600">${fmtInt(params.value)}</span> 条（${params.percent}%）`,
  },
  legend: {
    orient: 'vertical',
    right: 4,
    top: 'center',
    itemWidth: 8,
    itemHeight: 8,
    itemGap: 10,
    textStyle: { color: '#9fb8d8', fontSize: 11 },
    formatter: (name: string) => name,
  },
  series: [
    {
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['33%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: '#0a1c33', borderWidth: 2 },
      label: { show: false },
      labelLine: { show: false },
      emphasis: {
        scale: true,
        scaleSize: 4,
        label: { show: true, color: '#eaf5ff', fontSize: 11, formatter: '{b}\n{d}%' },
      },
      data: shareRows.value.map((item) => ({ name: item.name, value: item.value })),
    },
  ],
}))

const trendOption = computed<any>(() => {
  const dates = trendDates.value
  const interval = dates.length > 300 ? Math.ceil(dates.length / 12) : 'auto'
  const series: any[] = []
  if (mainSeries.value) {
    series.push({
      name: mainVarietyName.value,
      type: 'line',
      smooth: true,
      showSymbol: false,
      connectNulls: true,
      data: mainSeries.value.values,
      lineStyle: {
        width: 2.4,
        color: '#37d6f5',
        shadowColor: 'rgba(55, 214, 245, 0.55)',
        shadowBlur: 12,
      },
      itemStyle: { color: '#37d6f5' },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(55, 214, 245, 0.34)' },
            { offset: 1, color: 'rgba(55, 214, 245, 0)' },
          ],
        },
      },
    })
  }
  if (compositeSeries.value) {
    series.push({
      name: compositeName,
      type: 'line',
      smooth: true,
      showSymbol: false,
      connectNulls: true,
      data: compositeSeries.value.values,
      lineStyle: { width: 1.4, color: '#f7b955', type: 'dashed', opacity: 0.9 },
      itemStyle: { color: '#f7b955' },
    })
  }
  return {
    animationDuration: 700,
    grid: { left: 6, right: 14, top: 34, bottom: 6, containLabel: true },
    tooltip: {
      ...darkTooltip,
      trigger: 'axis',
      formatter: (params: any) => {
        const list = Array.isArray(params) ? params : [params]
        const head = list[0]?.axisValueLabel || list[0]?.axisValue || ''
        const body = list
          .map((item: any) => `${item.marker}${item.seriesName}：${fmtNum(item.value, 2)} 元/公斤`)
          .join('<br/>')
        return `${head}<br/>${body}`
      },
    },
    legend: {
      top: 4,
      right: 8,
      itemWidth: 14,
      itemHeight: 6,
      textStyle: { color: '#9fb8d8', fontSize: 11 },
      data: [mainVarietyName.value, compositeName].filter(Boolean),
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
      axisLine: { lineStyle: { color: 'rgba(96, 150, 220, 0.25)' } },
      axisTick: { show: false },
      axisLabel: { color: '#6f8fb8', fontSize: 10, interval, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#6f8fb8', fontSize: 10, formatter: (value: number) => fmtNum(value, 2) },
      splitLine: { lineStyle: { color: 'rgba(96, 150, 220, 0.10)' } },
    },
    series,
  }
})

const regionOption = computed<any>(() => {
  const rows = regionBars.value
  return {
    animationDuration: 700,
    grid: { left: 4, right: 62, top: 6, bottom: 4, containLabel: true },
    tooltip: {
      ...darkTooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(55, 214, 245, 0.06)' } },
      formatter: (params: any) => {
        const first = Array.isArray(params) ? params[0] : params
        const row = rows.find((item) => item.region === first.name)
        const yoy = row && typeof row.yoy_pct === 'number' ? `<br/>同比：${fmtPct(row.yoy_pct, 1)}` : ''
        return `${first.name}<br/>均价：<span style="color:#37d6f5;font-weight:600">${fmtNum(first.value, 2)}</span> 元/公斤${yoy}`
      },
    },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#6f8fb8', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(96, 150, 220, 0.10)' } },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map((item) => item.region),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#b9d2f2', fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        barWidth: 9,
        data: rows.map((item) => ({
          value: item.price,
          itemStyle: {
            borderRadius: [0, 4, 4, 0],
            color: (item.yoy_pct ?? 0) > 0 ? '#ff6b6b' : (item.yoy_pct ?? 0) < 0 ? '#2f9e8f' : '#3d8bff',
            shadowColor: 'rgba(55, 214, 245, 0.3)',
            shadowBlur: 5,
          },
        })),
        label: {
          show: true,
          position: 'right',
          color: '#8fd6ff',
          fontSize: 10,
          formatter: (params: any) => fmtNum(params.value, 2),
        },
      },
    ],
  }
})

function levelClass(level?: string) {
  if (level === '高' || level === '一级') return 'level-high'
  if (level === '中' || level === '二级') return 'level-mid'
  return 'level-low'
}

function changeClass(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'fc-muted'
  if (value > 0) return 'fc-up'
  if (value < 0) return 'fc-down'
  return 'fc-muted'
}

async function loadAll() {
  if (refreshing) return
  refreshing = true
  try {
    const [metaRes, summaryRes, trendRes, shareRes, alertRes, forecastRes] = await Promise.all([
      safeGet(api.get<MetaDicts>('/meta/dicts')),
      safeGet(api.get<DashboardSummary>('/dashboard/summary')),
      safeGet(api.get<TrendResp>('/dashboard/trend', { days: 90 })),
      safeGet(api.get<CategoryShareRow[]>('/dashboard/category-share')),
      safeGet(api.get<Paged<AlertRow>>('/alerts', { status: '待处理', page: 1, page_size: 8 })),
      safeGet(api.get<ForecastRow[]>('/dashboard/forecast-brief', { limit: 5 })),
    ])

    varieties.value = metaRes.ok && Array.isArray(metaRes.data?.varieties) ? metaRes.data.varieties : []
    summary.value = summaryRes.ok ? summaryRes.data || null : null
    trend.value = trendRes.ok ? trendRes.data || null : null
    categoryShare.value = shareRes.ok && Array.isArray(shareRes.data) ? shareRes.data : []
    alerts.value = alertRes.ok && Array.isArray(alertRes.data?.list) ? alertRes.data.list : []
    forecasts.value = forecastRes.ok && Array.isArray(forecastRes.data) ? forecastRes.data : []

    const coreFailures = [summaryRes, trendRes, shareRes].filter((result) => !result.ok).length
    const hasDashboardData = Boolean(summary.value || trend.value || categoryShare.value.length)
    offline.value = coreFailures >= 2 && !hasDashboardData

    const mainName = varietyRanking.value[0]?.name
    const matched = varieties.value.find((item) => item.name === mainName)
    const regionRes = await safeGet(
      api.get<RegionHeatRow[]>('/dashboard/region-heat', matched ? { variety_id: matched.id } : {}),
    )
    regionHeat.value = regionRes.ok && Array.isArray(regionRes.data) ? regionRes.data : []
  } finally {
    refreshing = false
    loading.value = false
  }
}

onMounted(() => {
  void loadAll()
  clockTimer = window.setInterval(() => {
    clock.value = new Date()
  }, 1000)
  refreshTimer = window.setInterval(() => {
    void loadAll()
  }, 30000)
})

onUnmounted(() => {
  if (clockTimer) {
    window.clearInterval(clockTimer)
    clockTimer = undefined
  }
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
})
</script>

<style scoped>
.screen {
  position: fixed;
  inset: 0;
  z-index: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #071322;
  color: #d8e7fb;
  font-family: 'Microsoft YaHei', 'PingFang SC', 'Helvetica Neue', Arial, sans-serif;
}

.screen::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(1200px 620px at 50% -8%, rgba(31, 95, 214, 0.36), transparent 62%),
    radial-gradient(960px 520px at 100% 108%, rgba(47, 158, 143, 0.16), transparent 60%),
    linear-gradient(180deg, #0b1f3a 0%, #081728 48%, #061120 100%);
  pointer-events: none;
}

.screen::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(64, 140, 255, 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(64, 140, 255, 0.055) 1px, transparent 1px);
  background-size: 44px 44px;
  -webkit-mask-image: radial-gradient(ellipse at 50% 40%, #000 30%, transparent 78%);
  mask-image: radial-gradient(ellipse at 50% 40%, #000 30%, transparent 78%);
  pointer-events: none;
}

.screen-header {
  position: relative;
  z-index: 2;
  flex: 0 0 64px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: 0 20px;
  border-bottom: 1px solid rgba(64, 140, 255, 0.2);
  background: linear-gradient(180deg, rgba(12, 32, 58, 0.92), rgba(8, 22, 40, 0.35));
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25);
}

.header-side {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-side.left {
  justify-content: flex-start;
}

.header-side.right {
  justify-content: flex-end;
}

.header-center {
  display: flex;
  align-items: center;
  gap: 14px;
}

.header-center h1 {
  margin: 0;
  font-size: 23px;
  font-weight: 700;
  letter-spacing: 3px;
  background: linear-gradient(180deg, #ffffff 12%, #8fd6ff 92%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  white-space: nowrap;
}

.deco-line {
  width: 62px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(55, 214, 245, 0.75));
  position: relative;
}

.deco-line::after {
  content: '';
  position: absolute;
  right: 0;
  top: -2px;
  width: 5px;
  height: 5px;
  background: #37d6f5;
  transform: rotate(45deg);
  box-shadow: 0 0 8px rgba(55, 214, 245, 0.8);
}

.deco-line.right {
  transform: scaleX(-1);
}

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #2f9e8f;
  box-shadow: 0 0 8px #2f9e8f;
  animation: pulse 1.8s ease-in-out infinite;
}

.live-dot.off {
  background: #d64545;
  box-shadow: 0 0 8px #d64545;
  animation: none;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

.live-text {
  font-size: 12px;
  color: #9fc0e4;
  letter-spacing: 1px;
}

.header-date {
  padding-left: 10px;
  border-left: 1px solid rgba(96, 150, 220, 0.25);
  font-size: 12px;
  color: #6f8fb8;
}

.clock {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  line-height: 1.25;
  margin-right: 6px;
}

.clock-date {
  font-size: 11px;
  color: #7fa6d0;
  letter-spacing: 1px;
}

.clock-time {
  font-size: 16px;
  color: #d9efff;
  font-family: 'Bahnschrift', 'Consolas', monospace;
  letter-spacing: 2px;
}

.refresh-btn,
.back-btn {
  --el-button-bg-color: rgba(31, 95, 214, 0.16);
  --el-button-border-color: rgba(64, 140, 255, 0.35);
  --el-button-text-color: #bcd8ff;
  --el-button-hover-bg-color: rgba(31, 95, 214, 0.32);
  --el-button-hover-border-color: rgba(64, 140, 255, 0.62);
  --el-button-hover-text-color: #ffffff;
  --el-button-active-bg-color: rgba(31, 95, 214, 0.4);
  --el-button-active-border-color: rgba(64, 140, 255, 0.7);
  border-radius: 6px;
  height: 30px;
}

.back-btn :deep(.el-icon) {
  margin-right: 5px;
}

.back-btn :deep(span) {
  letter-spacing: 1px;
}

.screen-body {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 356px minmax(0, 1fr) 396px;
  gap: 14px;
  padding: 14px 18px 16px;
}

.col {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
  min-height: 0;
}

.col-left .rank-panel {
  flex: 1.18 1 0;
}

.col-left .share-panel {
  flex: 1 1 0;
}

.col-center .trend-panel {
  flex: 1.15 1 0;
}

.col-center .region-panel {
  flex: 1 1 0;
}

.col-right .alert-panel {
  flex: 1.18 1 0;
}

.col-right .forecast-panel {
  flex: 1 1 0;
}

.panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(64, 140, 255, 0.18);
  background: linear-gradient(180deg, rgba(14, 36, 64, 0.9), rgba(8, 22, 40, 0.86));
  box-shadow:
    inset 0 0 34px rgba(31, 95, 214, 0.1),
    0 8px 20px rgba(0, 0, 0, 0.22);
  overflow: hidden;
}

.panel::before,
.panel::after {
  content: '';
  position: absolute;
  z-index: 1;
  width: 12px;
  height: 12px;
  pointer-events: none;
  border-color: rgba(55, 214, 245, 0.7);
  border-style: solid;
}

.panel::before {
  top: 0;
  left: 0;
  border-width: 2px 0 0 2px;
  border-top-left-radius: 10px;
}

.panel::after {
  right: 0;
  bottom: 0;
  border-width: 0 2px 2px 0;
  border-bottom-right-radius: 10px;
}

.panel-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-shrink: 0;
  margin-bottom: 8px;
}

.panel-head h3 {
  position: relative;
  margin: 0;
  padding-left: 9px;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 1px;
  color: #e6f2ff;
}

.panel-head h3::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 13px;
  border-radius: 2px;
  background: linear-gradient(180deg, #37d6f5, #1f5fd6);
  box-shadow: 0 0 8px rgba(55, 214, 245, 0.7);
}

.panel-sub {
  font-size: 11px;
  color: #6989ad;
  letter-spacing: 0.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-body {
  position: relative;
  flex: 1;
  min-height: 0;
}

.panel-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: 12px;
  letter-spacing: 1px;
  color: #5f7fa6;
}

.panel-body :deep(.chart-empty) {
  background: rgba(7, 20, 38, 0.88);
}

.panel-body :deep(.chart-empty .el-empty__description p) {
  color: #6f8fb8;
  font-size: 12px;
}

.kpi-grid {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.kpi-card {
  position: relative;
  overflow: hidden;
  min-height: 88px;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid rgba(64, 140, 255, 0.24);
  background: linear-gradient(135deg, rgba(31, 95, 214, 0.26), rgba(8, 22, 40, 0.55) 62%);
  box-shadow: inset 0 0 26px rgba(31, 95, 214, 0.12);
}

.kpi-card::after {
  content: '';
  position: absolute;
  right: -26px;
  top: -32px;
  width: 104px;
  height: 104px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(55, 214, 245, 0.22), transparent 68%);
}

.kpi-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  letter-spacing: 1px;
  color: #8fb0d6;
}

.kpi-label :deep(.el-icon) {
  color: #5fb6ff;
}

.tone-cyan {
  background: linear-gradient(135deg, rgba(47, 158, 143, 0.26), rgba(8, 22, 40, 0.55) 62%);
}

.tone-red {
  background: linear-gradient(135deg, rgba(214, 69, 69, 0.24), rgba(8, 22, 40, 0.55) 62%);
}

.tone-red .kpi-label :deep(.el-icon) {
  color: #ff8a8a;
}

.tone-amber {
  background: linear-gradient(135deg, rgba(217, 130, 43, 0.24), rgba(8, 22, 40, 0.55) 62%);
}

.tone-amber .kpi-label :deep(.el-icon) {
  color: #f7b955;
}

.kpi-value {
  margin-top: 4px;
  font-size: 28px;
  font-weight: 700;
  line-height: 1.15;
  color: #eef8ff;
  font-family: 'Bahnschrift', 'DIN Alternate', 'Consolas', sans-serif;
  text-shadow: 0 0 14px rgba(55, 214, 245, 0.3);
}

.kpi-value em {
  margin-left: 4px;
  font-size: 11px;
  font-style: normal;
  font-weight: 400;
  color: #7fa6d0;
  text-shadow: none;
}

.kpi-hint {
  margin-top: 2px;
  font-size: 11px;
  color: #6f8fb8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.alert-list {
  height: 100%;
  overflow-y: auto;
  padding-right: 2px;
}

.alert-list::-webkit-scrollbar {
  width: 3px;
}

.alert-list::-webkit-scrollbar-thumb {
  background: rgba(55, 214, 245, 0.3);
  border-radius: 3px;
}

.alert-item {
  display: flex;
  gap: 9px;
  margin-bottom: 8px;
  padding: 9px 10px;
  border-radius: 8px;
  border-left: 2px solid #d64545;
  background: rgba(255, 255, 255, 0.028);
  cursor: pointer;
  transition: background 0.2s;
}

.alert-item:hover {
  background: rgba(55, 214, 245, 0.08);
}

.alert-level {
  flex-shrink: 0;
  height: 20px;
  padding: 0 7px;
  border-radius: 4px;
  border: 1px solid rgba(214, 69, 69, 0.35);
  background: rgba(214, 69, 69, 0.18);
  color: #ffb4b4;
  font-size: 11px;
  line-height: 18px;
}

.alert-level.level-mid {
  border-color: rgba(217, 130, 43, 0.4);
  background: rgba(217, 130, 43, 0.18);
  color: #ffd18f;
}

.alert-level.level-low {
  border-color: rgba(47, 158, 143, 0.4);
  background: rgba(47, 158, 143, 0.16);
  color: #9fe3d8;
}

.alert-main {
  flex: 1;
  min-width: 0;
}

.alert-title {
  font-size: 12.5px;
  font-weight: 600;
  color: #dbe9ff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.alert-meta {
  display: flex;
  gap: 10px;
  margin-top: 3px;
  overflow: hidden;
  white-space: nowrap;
  font-size: 11px;
  color: #6f8fb8;
}

.fc-table {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.fc-row {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr 0.9fr 0.65fr;
  align-items: center;
  gap: 6px;
  height: 40px;
  padding: 0 8px;
  border-bottom: 1px solid rgba(96, 150, 220, 0.1);
  font-size: 12px;
}

.fc-head {
  height: 30px;
  border-bottom: none;
  border-radius: 6px;
  background: rgba(31, 95, 214, 0.12);
  color: #6f8fb8;
  font-size: 11px;
  letter-spacing: 1px;
}

.fc-name {
  font-weight: 600;
  color: #dbe9ff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fc-muted {
  color: #7fa0c4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fc-price {
  color: #8fd6ff;
  font-family: 'Bahnschrift', 'Consolas', sans-serif;
}

.fc-up {
  color: #ff7b7b;
}

.fc-down {
  color: #3fd3b4;
}

.fc-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #5f7fa6;
}

.fc-foot {
  margin-top: auto;
  padding: 8px 8px 2px;
  border-top: 1px solid rgba(96, 150, 220, 0.1);
  font-size: 11px;
  color: #5f7fa6;
}

@media (max-width: 1520px) {
  .screen-body {
    grid-template-columns: 320px minmax(0, 1fr) 360px;
    gap: 12px;
    padding: 12px 14px;
  }

  .header-center h1 {
    font-size: 20px;
    letter-spacing: 2px;
  }

  .kpi-value {
    font-size: 24px;
  }
}
</style>
