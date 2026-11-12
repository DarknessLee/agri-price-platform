<template>
  <div class="page price-monitor-page">
    <PageHeader title="价格监测" subtitle="多品种、多区域、多市场类型的价格明细与走势监测">
      <template #actions>
        <el-button type="primary" :loading="exporting" @click="exportCsv">
          <el-icon><Download /></el-icon>导出 CSV
        </el-button>
      </template>
    </PageHeader>

    <div class="price-kpis">
      <KpiCard
        label="平均价格"
        :value="fmtNum(stats?.avg, 2)"
        unit="元/公斤"
        icon="Money"
        tone="blue"
        :hint="`最新 ${fmtNum(stats?.latest, 2)} 元/公斤 · 中位数 ${fmtNum(stats?.median, 2)}`"
      />
      <KpiCard
        label="最高价格"
        :value="fmtNum(stats?.max, 2)"
        unit="元/公斤"
        icon="Top"
        tone="orange"
        :hint="`同比 ${fmtPct(stats?.yoy_pct)} · 环比 ${fmtPct(stats?.mom_pct)}`"
      />
      <KpiCard
        label="最低价格"
        :value="fmtNum(stats?.min, 2)"
        unit="元/公斤"
        icon="Bottom"
        tone="green"
        :hint="`统计记录 ${fmtInt(stats?.records)} 条`"
      />
      <KpiCard
        label="波动率"
        :value="fmtPct(stats?.volatility, 2, false)"
        icon="Odometer"
        tone="purple"
        hint="近 90 天价格标准差与均值之比"
      />
    </div>

    <section class="page-card">
      <div class="card-title">
        <span>价格走势</span>
        <div class="card-tools">
          <el-radio-group v-model="granularity" size="small" @change="loadSeries">
            <el-radio-button value="day">日</el-radio-button>
            <el-radio-button value="week">周</el-radio-button>
            <el-radio-button value="month">月</el-radio-button>
          </el-radio-group>
          <span class="unit-tip">单位：元/公斤</span>
        </div>
      </div>
      <BaseChart
        :option="seriesOption"
        :height="320"
        :loading="seriesLoading"
        :empty="!seriesCount"
        empty-text="暂无价格走势数据"
      />
    </section>

    <section class="page-card">
      <div class="card-title">
        <span>价格明细</span>
        <span class="unit-tip">共 {{ fmtInt(total) }} 条记录</span>
      </div>

      <div class="toolbar">
        <el-select v-model="varietyId" placeholder="全部品种" class="f-150" clearable>
          <el-option v-for="item in varieties" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <el-select v-model="regionId" placeholder="全部地区" class="f-140" clearable>
          <el-option v-for="item in regions" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <el-select v-model="marketType" placeholder="全部市场类型" class="f-130" clearable>
          <el-option v-for="item in marketTypes" :key="item" :label="item" :value="item" />
        </el-select>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          class="f-260"
          unlink-panels
        />
        <el-button type="primary" @click="query">
          <el-icon><Search /></el-icon>查询
        </el-button>
        <el-button @click="reset">
          <el-icon><RefreshLeft /></el-icon>重置
        </el-button>
      </div>

      <el-table v-loading="listLoading" :data="rows" size="small" stripe class="price-table">
        <el-table-column label="日期" width="104">
          <template #default="{ row }">{{ fmtDate(rowDate(row)) }}</template>
        </el-table-column>
        <el-table-column label="品种" width="96" show-overflow-tooltip>
          <template #default="{ row }">{{ row.variety || '—' }}</template>
        </el-table-column>
        <el-table-column label="地区" width="112" show-overflow-tooltip>
          <template #default="{ row }">{{ row.region || '—' }}</template>
        </el-table-column>
        <el-table-column label="市场" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.market || '—' }}</template>
        </el-table-column>
        <el-table-column label="市场类型" width="94" align="center">
          <template #default="{ row }">
            <el-tag :type="marketTypeTag(row.market_type)" size="small" effect="plain">{{ row.market_type || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="价格(元/公斤)" width="118" align="right">
          <template #default="{ row }"><span class="num-strong">{{ fmtNum(row.price, 2) }}</span></template>
        </el-table-column>
        <el-table-column label="最低价" width="92" align="right">
          <template #default="{ row }">{{ fmtNum(row.min_price, 2) }}</template>
        </el-table-column>
        <el-table-column label="最高价" width="92" align="right">
          <template #default="{ row }">{{ fmtNum(row.max_price, 2) }}</template>
        </el-table-column>
        <el-table-column label="成交量" width="100" align="right">
          <template #default="{ row }">{{ row.volume == null ? '—' : fmtInt(row.volume) }}</template>
        </el-table-column>
        <el-table-column label="质量标识" width="96" align="center">
          <template #default="{ row }">
            <el-tag :type="qualityType(row.quality_flag)" size="small">{{ row.quality_flag || '正常' }}</el-tag>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无价格明细数据" :image-size="72" />
        </template>
      </el-table>

      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @size-change="onSizeChange"
          @current-change="loadList"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import api, { type Paged } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import KpiCard from '@/components/KpiCard.vue'
import BaseChart from '@/components/BaseChart.vue'
import { useAuthStore } from '@/stores/auth'
import { fmtDate, fmtInt, fmtNum, fmtPct } from '@/utils/format'
import type { DictOption, MetaDicts } from '@/types'

interface PriceListRow {
  id: number
  date?: string
  price_date?: string
  variety?: string
  region?: string
  market?: string
  market_type?: string
  price?: number
  min_price?: number
  max_price?: number
  volume?: number
  unit?: string
  quality_flag?: string
}

interface PriceStats {
  avg?: number
  max?: number
  min?: number
  latest?: number
  prev?: number
  yoy_pct?: number
  mom_pct?: number
  volatility?: number
  median?: number
  records?: number
  updated_at?: string
}

interface SeriesResp {
  dates: string[]
  series: Array<{ name: string; values: number[] }>
  unit?: string
}

const auth = useAuthStore()
const palette = ['#1f5fd6', '#2f9e8f', '#d9822b', '#d64545', '#6f42c1']

const varieties = ref<DictOption[]>([])
const regions = ref<DictOption[]>([])
const marketTypes = ref<string[]>([])

const varietyId = ref<number | null>(null)
const regionId = ref<number | null>(null)
const marketType = ref('')
const dateRange = ref<[string, string] | null>([dayjs().subtract(29, 'day').format('YYYY-MM-DD'), dayjs().format('YYYY-MM-DD')])
const granularity = ref<'day' | 'week' | 'month'>('day')

const rows = ref<PriceListRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const listLoading = ref(false)

const stats = ref<PriceStats | null>(null)
const seriesData = ref<SeriesResp | null>(null)
const seriesLoading = ref(false)
const exporting = ref(false)

let warned = false
function warnUnavailable() {
  if (warned) return
  warned = true
  ElMessage.warning('数据服务暂不可用')
}

const seriesCount = computed(() => (seriesData.value?.series || []).filter((item) => item.values && item.values.length).length)

function filterParams(): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  if (varietyId.value !== null) params.variety_id = varietyId.value
  if (regionId.value !== null) params.region_id = regionId.value
  if (marketType.value) params.market_type = marketType.value
  if (dateRange.value?.[0]) params.start = dateRange.value[0]
  if (dateRange.value?.[1]) params.end = dateRange.value[1]
  return params
}

function rowDate(row: PriceListRow): string {
  return row.date || row.price_date || ''
}

function marketTypeTag(value?: string): 'primary' | 'success' | 'info' | 'warning' | 'danger' {
  if (value === '批发') return 'primary'
  if (value === '零售') return 'warning'
  if (value === '产地') return 'success'
  return 'info'
}

function qualityType(value?: string): 'success' | 'info' | 'warning' | 'danger' {
  if (!value) return 'success'
  if (/正常|合格|有效|ok|pass|good/i.test(value)) return 'success'
  if (/缺失|空值|missing/i.test(value)) return 'info'
  if (/异常|离群|错误|无效|error|outlier|invalid/i.test(value)) return 'danger'
  return 'warning'
}

function axisInterval(count: number): number | 'auto' {
  if (count <= 300) return 'auto'
  return Math.ceil(count / 12)
}

const seriesOption = computed<any>(() => {
  const data = seriesData.value
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
    legend: { top: 0, right: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: '#5b6b7f', fontSize: 12 } },
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

async function loadMeta() {
  try {
    const data = await api.get<MetaDicts>('/meta/dicts')
    varieties.value = Array.isArray(data?.varieties) ? data.varieties : []
    regions.value = Array.isArray(data?.regions) ? data.regions : []
    marketTypes.value = Array.isArray(data?.market_types) ? data.market_types : []
    varietyId.value = varieties.value[0]?.id ?? null
  } catch {
    warnUnavailable()
    varieties.value = []
    regions.value = []
    marketTypes.value = []
  }
}

async function loadList() {
  listLoading.value = true
  try {
    const data = await api.get<Paged<PriceListRow>>('/prices', {
      ...filterParams(),
      page: page.value,
      page_size: pageSize.value,
    })
    rows.value = Array.isArray(data?.list) ? data.list : []
    total.value = Number(data?.total ?? 0)
  } catch {
    warnUnavailable()
    rows.value = []
    total.value = 0
  } finally {
    listLoading.value = false
  }
}

async function loadStats() {
  if (varietyId.value === null) {
    stats.value = null
    return
  }
  try {
    stats.value = await api.get<PriceStats>('/prices/stats', {
      variety_id: varietyId.value,
      region_id: regionId.value ?? undefined,
      days: 90,
    })
  } catch {
    warnUnavailable()
    stats.value = null
  }
}

async function loadSeries() {
  if (varietyId.value === null) {
    seriesData.value = null
    return
  }
  seriesLoading.value = true
  try {
    seriesData.value = await api.get<SeriesResp>('/prices/series', {
      ...filterParams(),
      granularity: granularity.value,
    })
  } catch {
    warnUnavailable()
    seriesData.value = null
  } finally {
    seriesLoading.value = false
  }
}

function query() {
  page.value = 1
  loadList()
  loadStats()
  loadSeries()
}

function reset() {
  varietyId.value = varieties.value[0]?.id ?? null
  regionId.value = null
  marketType.value = ''
  dateRange.value = [dayjs().subtract(29, 'day').format('YYYY-MM-DD'), dayjs().format('YYYY-MM-DD')]
  query()
}

function onSizeChange(size: number) {
  pageSize.value = size
  page.value = 1
  loadList()
}

async function exportCsv() {
  if (!auth.hasPerm('monitor:export')) {
    ElMessage.warning('当前账号无价格数据导出权限')
    return
  }
  exporting.value = true
  try {
    await api.download('/prices/export', filterParams(), `价格监测_${dayjs().format('YYYYMMDD_HHmmss')}.csv`)
    ElMessage.success('导出已开始')
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  await loadMeta()
  await Promise.all([loadList(), loadStats(), loadSeries()])
})
</script>

<style scoped>
.price-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.card-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}

.unit-tip {
  font-size: 12px;
  color: #8b9aae;
  white-space: nowrap;
}

.f-150 {
  width: 150px;
}

.f-140 {
  width: 140px;
}

.f-130 {
  width: 130px;
}

.f-260 {
  width: 260px;
}

.price-table {
  width: 100%;
}

.num-strong {
  font-weight: 600;
  color: #16233a;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 1100px) {
  .price-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
