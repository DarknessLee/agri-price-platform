<template>
  <div class="page analysis-page">
    <PageHeader title="监测分析" subtitle="区域价差、品种比价与季节波动多维分析">
      <template #actions>
        <el-button :loading="spreadLoading || compareLoading || seasonLoading" @click="loadAll">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
      </template>
    </PageHeader>

    <section class="page-card filter-card">
      <div class="toolbar filter-toolbar">
        <span class="filter-label">品种</span>
        <el-select v-model="varietyId" placeholder="选择品种" class="f-160" @change="loadAll">
          <el-option v-for="item in varieties" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <span class="filter-label">地区</span>
        <el-select v-model="regionId" placeholder="全部地区" class="f-150" clearable @change="loadAll">
          <el-option v-for="item in regions" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <span class="filter-label">分析区间</span>
        <el-select v-model="days" class="f-120" @change="loadAll">
          <el-option label="近 30 天" :value="30" />
          <el-option label="近 60 天" :value="60" />
          <el-option label="近 90 天" :value="90" />
        </el-select>
        <el-button type="primary" @click="loadAll">
          <el-icon><Search /></el-icon>查询
        </el-button>
        <el-button @click="reset">
          <el-icon><RefreshLeft /></el-icon>重置
        </el-button>
      </div>
    </section>

    <div class="chart-grid-2">
      <section class="page-card">
        <div class="card-title">
          <span>区域价差</span>
          <span class="unit-tip">单位：元/公斤</span>
        </div>
        <BaseChart
          :option="spreadOption"
          :height="320"
          :loading="spreadLoading"
          :empty="!spreadStats.length"
          empty-text="暂无区域价差数据"
        />
      </section>

      <section class="page-card">
        <div class="card-title">
          <span>品种比价指数</span>
          <span class="unit-tip">以区间首日 = 100</span>
        </div>
        <BaseChart
          :option="compareOption"
          :height="320"
          :loading="compareLoading"
          :empty="!compareCount"
          empty-text="暂无品种比价数据"
        />
      </section>
    </div>

    <section class="page-card">
      <div class="card-title">
        <span>季节指数</span>
        <span class="unit-tip">近 3 年同月平均指数，100 代表常年水平</span>
      </div>
      <BaseChart
        :option="seasonOption"
        :height="320"
        :loading="seasonLoading"
        :empty="!seasonData?.indices?.length"
        empty-text="暂无季节指数数据"
      />
    </section>

    <section class="page-card">
      <div class="card-title">
        <span>指标说明</span>
      </div>
      <div class="guide-grid">
        <div v-for="item in guideItems" :key="item.title" class="guide-item">
          <div class="guide-head">
            <el-icon><component :is="item.icon" /></el-icon>
            <strong>{{ item.title }}</strong>
          </div>
          <p>{{ item.desc }}</p>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import BaseChart from '@/components/BaseChart.vue'
import { fmtNum } from '@/utils/format'
import type { DictOption, MetaDicts } from '@/types'

interface SpreadSeries {
  region: string
  values: number[]
}

interface SpreadStat {
  region: string
  avg: number
  min: number
  max: number
  spread: number
}

interface SpreadResp {
  dates: string[]
  series: SpreadSeries[]
  stats: SpreadStat[]
}

interface CompareResp {
  dates: string[]
  series: Array<{ variety: string; values: number[] }>
  normalized?: boolean
}

interface SeasonResp {
  months: number[]
  indices: number[]
  unit?: string
}

const palette = ['#1f5fd6', '#2f9e8f', '#d9822b', '#d64545', '#6f42c1', '#3a8ee6', '#8a9b6e', '#b5729b']

const varieties = ref<DictOption[]>([])
const regions = ref<DictOption[]>([])
const varietyId = ref<number | null>(null)
const regionId = ref<number | null>(null)
const days = ref(30)

const spreadData = ref<SpreadResp | null>(null)
const compareData = ref<CompareResp | null>(null)
const seasonData = ref<SeasonResp | null>(null)

const spreadLoading = ref(false)
const compareLoading = ref(false)
const seasonLoading = ref(false)

let warned = false
function warnUnavailable() {
  if (warned) return
  warned = true
  ElMessage.warning('数据服务暂不可用')
}

const spreadStats = computed<SpreadStat[]>(() => {
  const stats = spreadData.value?.stats
  if (!Array.isArray(stats) || !stats.length) return []
  return [...stats].sort((a, b) => (b.avg || 0) - (a.avg || 0))
})

const compareCount = computed(() => (compareData.value?.series || []).filter((item) => item.values && item.values.length).length)

function axisInterval(count: number): number | 'auto' {
  if (count <= 300) return 'auto'
  return Math.ceil(count / 12)
}

const spreadOption = computed<any>(() => {
  const rows = spreadStats.value
  return {
    color: ['#1f5fd6', '#d9822b'],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : [params]
        const name = (list[0] as { name?: string } | undefined)?.name
        const row = rows.find((item) => item.region === name)
        if (!row) return ''
        return [
          `<div style="font-weight:600;margin-bottom:4px">${row.region}</div>`,
          `平均价：${fmtNum(row.avg, 2)} 元/公斤`,
          `最低价：${fmtNum(row.min, 2)} 元/公斤`,
          `最高价：${fmtNum(row.max, 2)} 元/公斤`,
          `价差：${fmtNum(row.spread, 2)} 元/公斤`,
        ].join('<br/>')
      },
    },
    legend: { top: 0, right: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: '#5b6b7f', fontSize: 12 } },
    grid: { left: 8, right: 12, top: 40, bottom: 6, containLabel: true },
    xAxis: {
      type: 'category',
      data: rows.map((row) => row.region),
      axisLine: { lineStyle: { color: '#e4e9f2' } },
      axisTick: { show: false },
      axisLabel: { color: '#5b6b7f', fontSize: 11, interval: 0, rotate: rows.length > 8 ? 30 : 0 },
    },
    yAxis: {
      type: 'value',
      scale: true,
      splitLine: { lineStyle: { color: '#f0f3f9' } },
      axisLabel: { color: '#7b8ba1', fontSize: 11, formatter: (value: number) => fmtNum(value, 0) },
    },
    series: [
      {
        name: '平均价',
        type: 'bar',
        barMaxWidth: 22,
        itemStyle: { borderRadius: [4, 4, 0, 0] },
        data: rows.map((row) => row.avg),
      },
      {
        name: '价差',
        type: 'bar',
        barMaxWidth: 22,
        itemStyle: { borderRadius: [4, 4, 0, 0] },
        data: rows.map((row) => row.spread),
      },
    ],
  }
})

const compareOption = computed<any>(() => {
  const data = compareData.value
  const dates = data?.dates || []
  const source = (data?.series || []).filter((item) => item.values && item.values.length)
  const series = source.map((item, index) => ({
    name: item.variety || `品种${index + 1}`,
    type: 'line',
    smooth: true,
    showSymbol: dates.length <= 45,
    symbolSize: 4,
    data: item.values,
    lineStyle: { width: source.length > 4 ? 1.6 : 2 },
    markLine:
      index === 0
        ? {
            silent: true,
            symbol: 'none',
            lineStyle: { type: 'dashed', color: '#a3b0c2', width: 1 },
            label: { formatter: '基准 100', color: '#8b9aae', position: 'insideEndTop' },
            data: [{ yAxis: 100 }],
          }
        : undefined,
  }))
  return {
    color: palette,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: '#b9c7dd' } },
      valueFormatter: (value: unknown) => (value === null || value === undefined ? '—' : fmtNum(Number(value), 2)),
    },
    legend: { top: 0, right: 0, type: 'scroll', icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: '#5b6b7f', fontSize: 12 } },
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

const seasonOption = computed<any>(() => {
  const data = seasonData.value
  const months = (data?.months || []).map((month) => `${month}月`)
  const indices = data?.indices || []
  return {
    color: ['#1f5fd6', '#a3b0c2'],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: unknown) => (value === null || value === undefined ? '—' : fmtNum(Number(value), 2)),
    },
    legend: { top: 0, right: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: '#5b6b7f', fontSize: 12 } },
    grid: { left: 8, right: 16, top: 40, bottom: 6, containLabel: true },
    xAxis: {
      type: 'category',
      data: months,
      axisLine: { lineStyle: { color: '#e4e9f2' } },
      axisTick: { show: false },
      axisLabel: { color: '#5b6b7f', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      scale: true,
      name: '季节指数',
      nameTextStyle: { color: '#8b9aae', fontSize: 11, padding: [0, 0, 0, -28] },
      splitLine: { lineStyle: { color: '#f0f3f9' } },
      axisLabel: { color: '#7b8ba1', fontSize: 11, formatter: (value: number) => fmtNum(value, 0) },
    },
    series: [
      {
        name: '季节指数',
        type: 'bar',
        barMaxWidth: 30,
        data: indices.map((value) => ({
          value,
          itemStyle: { borderRadius: [4, 4, 0, 0], color: value >= 100 ? '#d9822b' : '#1f5fd6' },
        })),
        label: { show: true, position: 'top', color: '#8b9aae', fontSize: 10, formatter: (params: any) => fmtNum(params.value, 0) },
      },
      {
        name: '基准线',
        type: 'line',
        symbol: 'none',
        lineStyle: { type: 'dashed', color: '#a3b0c2', width: 1 },
        data: months.map(() => 100),
      },
    ],
  }
})

const guideItems = [
  {
    title: '同比',
    icon: 'TrendCharts',
    desc: '本期价格与上年同期价格的变动幅度，用于判断年度价格趋势与周期性变化。',
  },
  {
    title: '环比',
    icon: 'DataLine',
    desc: '本期价格与上一统计期（日、周、月）价格的变动幅度，反映短期供需与市场波动。',
  },
  {
    title: '波动率',
    icon: 'Odometer',
    desc: '区间内价格标准差与均值的比值，数值越高说明价格越不稳定，用于衡量市场风险。',
  },
  {
    title: '价差与比价口径',
    icon: 'ScaleToOriginal',
    desc: '区域价差为同品种各地区价格极差；品种比价指数以区间首日价格为 100，消除量纲后横向比较走势。',
  },
]

async function loadMeta() {
  try {
    const data = await api.get<MetaDicts>('/meta/dicts')
    varieties.value = Array.isArray(data?.varieties) ? data.varieties : []
    regions.value = Array.isArray(data?.regions) ? data.regions : []
    if (varietyId.value === null) varietyId.value = varieties.value[0]?.id ?? null
  } catch {
    warnUnavailable()
    varieties.value = []
    regions.value = []
  }
}

async function loadSpread() {
  if (varietyId.value === null) {
    spreadData.value = null
    return
  }
  spreadLoading.value = true
  try {
    spreadData.value = await api.get<SpreadResp>('/prices/region-spread', {
      variety_id: varietyId.value,
      days: days.value,
    })
  } catch {
    warnUnavailable()
    spreadData.value = null
  } finally {
    spreadLoading.value = false
  }
}

async function loadCompare() {
  compareLoading.value = true
  try {
    compareData.value = await api.get<CompareResp>('/prices/variety-compare', {
      region_id: regionId.value ?? undefined,
      days: days.value,
    })
  } catch {
    warnUnavailable()
    compareData.value = null
  } finally {
    compareLoading.value = false
  }
}

async function loadSeason() {
  if (varietyId.value === null) {
    seasonData.value = null
    return
  }
  seasonLoading.value = true
  try {
    seasonData.value = await api.get<SeasonResp>('/prices/seasonality', {
      variety_id: varietyId.value,
      region_id: regionId.value ?? undefined,
      years: 3,
    })
  } catch {
    warnUnavailable()
    seasonData.value = null
  } finally {
    seasonLoading.value = false
  }
}

async function loadAll() {
  if (!varieties.value.length) await loadMeta()
  await Promise.all([loadSpread(), loadCompare(), loadSeason()])
}

function reset() {
  varietyId.value = varieties.value[0]?.id ?? null
  regionId.value = null
  days.value = 30
  loadAll()
}

onMounted(loadAll)
</script>

<style scoped>
.filter-card {
  padding: 14px 20px;
}

.filter-toolbar {
  margin-bottom: 0;
}

.filter-label {
  font-size: 13px;
  color: #5b6b7f;
}

.unit-tip {
  font-size: 12px;
  color: #8b9aae;
  white-space: nowrap;
}

.f-160 {
  width: 160px;
}

.f-150 {
  width: 150px;
}

.f-120 {
  width: 120px;
}

.guide-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.guide-item {
  padding: 14px 16px;
  border: 1px solid #eef2f9;
  border-radius: 8px;
  background: #f9fbff;
}

.guide-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #1c2a3a;
}

.guide-head .el-icon {
  color: #1f5fd6;
  font-size: 16px;
}

.guide-item p {
  margin: 8px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: #6b7c93;
}

@media (max-width: 1100px) {
  .guide-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
