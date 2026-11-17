<template>
  <div class="h5-page">
    <div class="h5-hero">
      <h1>价格行情</h1>
      <p>{{ heroSub }}</p>
    </div>

    <div class="h5-card filter-card">
      <VanTabs v-model:active="varietyIndex" class="variety-tabs" shrink swipe-threshold="3">
        <VanTab v-for="item in varieties" :key="item.id" :title="item.name" />
      </VanTabs>

      <VanDropdownMenu class="region-menu">
        <VanDropdownItem v-model="regionValue" :options="regionOptions" />
      </VanDropdownMenu>

      <div class="filter-line">
        <span class="filter-label">粒度</span>
        <div class="seg">
          <button
            v-for="item in granOptions"
            :key="item.value"
            type="button"
            class="seg-btn"
            :class="{ active: gran === item.value }"
            @click="gran = item.value"
          >
            {{ item.label }}
          </button>
        </div>
      </div>

      <div class="filter-line">
        <span class="filter-label">市场</span>
        <div class="seg">
          <button
            v-for="item in marketOptions"
            :key="item.value"
            type="button"
            class="seg-btn"
            :class="{ active: marketType === item.value }"
            @click="marketType = item.value"
          >
            {{ item.label }}
          </button>
        </div>
      </div>
    </div>

    <div class="h5-kpi-grid">
      <div v-for="item in kpiItems" :key="item.label" class="h5-kpi">
        <div class="h5-kpi-label">{{ item.label }}</div>
        <div class="h5-kpi-value">
          {{ item.value }}
          <small v-if="item.unit">{{ item.unit }}</small>
        </div>
        <div class="h5-kpi-hint">{{ item.hint }}</div>
      </div>
    </div>

    <div class="h5-card chart-card">
      <div class="h5-card-title">
        <span>价格走势</span>
        <span class="h5-muted">{{ granLabel }} · {{ unit }}</span>
      </div>
      <AppChart :option="chartOption" :height="210" :empty="!hasTrend" empty-text="暂无走势数据" />
      <div v-if="visibleSeries.length" class="legend">
        <span v-for="(item, index) in visibleSeries" :key="item.name" class="legend-item">
          <i :style="{ background: palette[index % palette.length] }" />
          {{ item.name }}
        </span>
      </div>
    </div>

    <div class="h5-card">
      <div class="h5-row">
        <span class="h5-row-label">最新价格</span>
        <span class="h5-row-value">{{ fmtNum(latestPrice) }} {{ unit }}</span>
      </div>
      <div class="h5-row">
        <span class="h5-row-label">环比变化</span>
        <span class="h5-row-value" :class="trendClass(momPct)">{{ fmtPct(momPct) }}</span>
      </div>
      <div class="h5-row">
        <span class="h5-row-label">样本记录</span>
        <span class="h5-row-value">{{ fmtInt(records) }} 条</span>
      </div>
    </div>

    <div class="h5-card list-card">
      <div class="h5-card-title">
        <span>价格明细</span>
        <span class="h5-muted">共 {{ fmtInt(total) }} 条</span>
      </div>
      <VanPullRefresh v-model="refreshing" @refresh="onRefresh">
        <VanList
          v-model:loading="listLoading"
          :finished="finished"
          :finished-text="finishedText"
          :immediate-check="false"
          @load="loadMore"
        >
          <div v-if="!rows.length && !listLoading" class="h5-empty">暂无价格明细</div>
          <div v-for="(row, index) in rows" :key="row.id" class="price-row">
            <div class="price-row-main">
              <div class="price-row-title">
                <span class="price-date">{{ fmtDate(row.date) }}</span>
                <VanTag v-if="row.market_type" plain type="primary">{{ row.market_type }}</VanTag>
                <VanTag v-if="row.quality_flag && row.quality_flag !== '正常'" plain :type="qualityType(row.quality_flag)">
                  {{ row.quality_flag }}
                </VanTag>
              </div>
              <div class="price-row-sub">
                {{ row.market || '-' }}
                <template v-if="row.region"> · {{ row.region }}</template>
              </div>
            </div>
            <div class="price-row-side">
              <div class="price-value">{{ fmtNum(row.price) }}<small>{{ row.unit || unit }}</small></div>
              <div class="price-change" :class="trendClass(changePct(index))">{{ changeText(index) }}</div>
            </div>
          </div>
        </VanList>
      </VanPullRefresh>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import {
  DropdownItem as VanDropdownItem,
  DropdownMenu as VanDropdownMenu,
  List as VanList,
  PullRefresh as VanPullRefresh,
  Tab as VanTab,
  Tabs as VanTabs,
  Tag as VanTag,
  showFailToast,
} from 'vant';

import { ApiError } from '@/api/client';
import { metaApi, priceApi } from '@/api';
import AppChart from '@/components/AppChart.vue';
import type { MetaDicts, PriceRow, PriceStats, TrendData } from '@/types';
import { fmtDate, fmtInt, fmtNum, fmtPct, shortDate, trendClass } from '@/utils/format';

interface RegionOption {
  text: string;
  value: number;
}

const palette = ['#1f5fd6', '#e08b1f', '#1f9d63', '#8b5cf6'];
const PAGE_SIZE = 15;

const dicts = ref<MetaDicts | null>(null);
const ready = ref(false);
const varietyIndex = ref(0);
const regionValue = ref(0);
const gran = ref<'day' | 'week' | 'month'>('day');
const marketType = ref('');
const stats = ref<PriceStats | null>(null);
const series = ref<TrendData | null>(null);
const rows = ref<PriceRow[]>([]);
const total = ref(0);
const currentPage = ref(1);
const listLoading = ref(false);
const finished = ref(false);
const refreshing = ref(false);

const varieties = computed(() => dicts.value?.varieties || []);
const varietyId = computed<number | undefined>(() => varieties.value[varietyIndex.value]?.id);
const varietyName = computed(() => varieties.value[varietyIndex.value]?.name || '');

const regionOptions = computed<RegionOption[]>(() => [
  { text: '全部地区', value: 0 },
  ...(dicts.value?.regions || []).map((item) => ({ text: item.name, value: item.id })),
]);

const granOptions: { label: string; value: 'day' | 'week' | 'month' }[] = [
  { label: '日', value: 'day' },
  { label: '周', value: 'week' },
  { label: '月', value: 'month' },
];

const marketOptions = [
  { label: '全部', value: '' },
  { label: '批发', value: '批发' },
  { label: '零售', value: '零售' },
];

const granLabel = computed(() => granOptions.find((item) => item.value === gran.value)?.label || '');

const unit = computed<string>(() => {
  const value = series.value?.unit;
  return value === '元/公斤' || !value ? '元/公斤' : value;
});

const latestPrice = computed<number | null>(() => {
  const value = stats.value?.latest;
  return typeof value === 'number' ? value : null;
});

const momPct = computed<number | null>(() => {
  const value = stats.value?.mom_pct;
  return typeof value === 'number' ? value : null;
});

const records = computed<number | null>(() => {
  const value = stats.value?.records ?? stats.value?.record_count;
  return typeof value === 'number' ? value : null;
});

const kpiItems = computed(() => {
  const avg = stats.value?.avg_price ?? stats.value?.avg;
  const max = stats.value?.max_price ?? stats.value?.max;
  const min = stats.value?.min_price ?? stats.value?.min;
  const volatility = stats.value?.volatility;
  return [
    { label: '平均价', value: fmtNum(avg), unit: unit.value, hint: '近 90 天均价' },
    { label: '最高价', value: fmtNum(max), unit: unit.value, hint: '区间最高' },
    { label: '最低价', value: fmtNum(min), unit: unit.value, hint: '区间最低' },
    { label: '波动率', value: fmtNum(volatility), unit: '%', hint: '近 30 日波动' },
  ];
});

const heroSub = computed(() => {
  const dates = series.value?.dates || [];
  const lastDate = dates.length ? fmtDate(dates[dates.length - 1]) : '-';
  const name = varietyName.value || '全部品种';
  const region = regionValue.value === 0
    ? '全部地区'
    : regionOptions.value.find((item) => item.value === regionValue.value)?.text || '全部地区';
  return `${name} · ${region} · 数据更新至 ${lastDate}`;
});

const visibleSeries = computed(() => (series.value?.series || []).filter((item) => (item.values || []).length > 0));
const hasTrend = computed(() => (series.value?.dates || []).length > 0 && visibleSeries.value.length > 0);

function hexToRgba(hex: string, alpha: number): string {
  const value = hex.replace('#', '');
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const chartOption = computed<Record<string, unknown>>(() => {
  const dates = series.value?.dates || [];
  return {
    color: palette,
    grid: { left: 4, right: 10, top: 14, bottom: 0, containLabel: true },
    tooltip: { trigger: 'axis', confine: true, valueFormatter: (value: number) => fmtNum(value) },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
      axisLine: { lineStyle: { color: '#e6eaf2' } },
      axisTick: { show: false },
      axisLabel: {
        fontSize: 10,
        color: '#8a94a6',
        hideOverlap: true,
        formatter: (value: string) => (gran.value === 'month' ? value.slice(0, 7) : shortDate(value)),
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { fontSize: 10, color: '#8a94a6', formatter: (value: number) => fmtNum(value, 1) },
      splitLine: { lineStyle: { color: '#eef1f7', type: 'dashed' } },
    },
    series: visibleSeries.value.map((item, index) => {
      const color = palette[index % palette.length];
      return {
        name: item.name,
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color },
        itemStyle: { color },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: hexToRgba(color, 0.18) },
              { offset: 1, color: hexToRgba(color, 0.01) },
            ],
          },
        },
        data: item.values || [],
      };
    }),
  };
});

function qualityType(flag: string): 'danger' | 'warning' | 'primary' {
  if (flag === '疑似异常') return 'danger';
  if (flag === '缺失' || flag === '缺失估算') return 'warning';
  return 'primary';
}

function changePct(index: number): number | null {
  const current = rows.value[index];
  const previous = rows.value[index + 1];
  if (!current || !previous || !previous.price) return null;
  return ((current.price - previous.price) / previous.price) * 100;
}

function changeText(index: number): string {
  const value = changePct(index);
  if (value === null) return '-';
  const arrow = value > 0 ? '↑' : value < 0 ? '↓' : '';
  return arrow ? `${arrow} ${fmtPct(value)}` : fmtPct(value);
}

const finishedText = computed(() => (total.value > 0 ? '没有更多了' : ''));

function showError(error: unknown, fallback: string = '数据服务暂不可用'): void {
  const message = error instanceof ApiError && error.message ? error.message : fallback;
  showFailToast(message);
}

async function loadDicts(): Promise<void> {
  try {
    dicts.value = await metaApi.dicts();
  } catch (error) {
    showError(error, '基础数据加载失败');
  }
}

async function loadStats(): Promise<void> {
  if (!varietyId.value) return;
  try {
    stats.value = await priceApi.stats({
      variety_id: varietyId.value,
      region_id: regionValue.value || undefined,
    });
  } catch (error) {
    stats.value = null;
    showError(error);
  }
}

async function loadSeries(): Promise<void> {
  if (!varietyId.value) return;
  try {
    series.value = await priceApi.series({
      variety_id: varietyId.value,
      region_id: regionValue.value || undefined,
      granularity: gran.value,
    });
  } catch (error) {
    series.value = null;
    showError(error);
  }
}

async function loadPage(page = 1): Promise<void> {
  if (!varietyId.value) {
    listLoading.value = false;
    return;
  }
  listLoading.value = true;
  try {
    const data = await priceApi.list({
      variety_id: varietyId.value,
      region_id: regionValue.value || undefined,
      market_type: marketType.value || undefined,
      page,
      page_size: PAGE_SIZE,
    });
    const list = data.list || [];
    rows.value = page === 1 ? list : rows.value.concat(list);
    total.value = data.total || 0;
    currentPage.value = page;
    finished.value = rows.value.length >= total.value;
  } catch (error) {
    showError(error);
    if (page === 1) rows.value = [];
    finished.value = false;
  } finally {
    listLoading.value = false;
  }
}

function resetList(): void {
  rows.value = [];
  total.value = 0;
  currentPage.value = 1;
  finished.value = false;
  void loadPage(1);
}

async function loadMore(): Promise<void> {
  if (finished.value) {
    listLoading.value = false;
    return;
  }
  await loadPage(currentPage.value + 1);
}

async function onRefresh(): Promise<void> {
  try {
    await Promise.all([loadStats(), loadSeries(), loadPage(1)]);
  } finally {
    refreshing.value = false;
  }
}

function reloadAll(): void {
  void loadStats();
  void loadSeries();
  resetList();
}

watch(varietyIndex, () => {
  if (ready.value) reloadAll();
});
watch(regionValue, () => {
  if (ready.value) reloadAll();
});
watch(gran, () => {
  if (ready.value) void loadSeries();
});
watch(marketType, () => {
  if (ready.value) {
    void loadSeries();
    resetList();
  }
});

onMounted(async () => {
  await loadDicts();
  ready.value = true;
  reloadAll();
});
</script>

<style scoped>
.filter-card {
  padding-top: 4px;
}

.variety-tabs {
  margin-bottom: 2px;
}

.variety-tabs :deep(.van-tab) {
  padding: 0 12px;
  font-size: 13px;
}

.variety-tabs :deep(.van-tabs__line) {
  width: 22px;
  border-radius: 2px;
}

.region-menu {
  margin: 2px 0;
}

.region-menu :deep(.van-dropdown-menu__bar) {
  height: 38px;
  background: transparent;
  box-shadow: none;
}

.region-menu :deep(.van-dropdown-menu__title) {
  font-size: 13px;
  color: var(--ap-text-2);
}

.filter-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}

.filter-label {
  flex-shrink: 0;
  width: 28px;
  font-size: 12px;
  color: var(--ap-muted);
}

.seg {
  flex: 1;
  display: flex;
  gap: 4px;
  min-width: 0;
  padding: 3px;
  border-radius: 16px;
  background: #f1f4f9;
}

.seg-btn {
  flex: 1;
  min-width: 0;
  height: 30px;
  padding: 0 4px;
  border: none;
  border-radius: 13px;
  background: transparent;
  color: var(--ap-text-2);
  font-size: 13px;
  line-height: 30px;
}

.seg-btn.active {
  background: #fff;
  color: var(--ap-primary);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(18, 35, 63, 0.12);
}

.chart-card {
  padding-bottom: 6px;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 2px 2px 4px;
  font-size: 11px;
  color: var(--ap-text-2);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.legend-item i {
  width: 8px;
  height: 3px;
  border-radius: 2px;
}

.list-card {
  padding-bottom: 4px;
}

.list-card :deep(.van-pull-refresh) {
  overflow: visible;
}

.price-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid var(--ap-border);
}

.price-row:last-child {
  border-bottom: none;
}

.price-row-main {
  flex: 1;
  min-width: 0;
}

.price-row-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.price-date {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--ap-text);
}

.price-row-title :deep(.van-tag) {
  flex-shrink: 0;
  font-size: 11px;
  line-height: 16px;
}

.price-row-sub {
  margin-top: 2px;
  overflow: hidden;
  font-size: 12px;
  color: var(--ap-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.price-row-side {
  flex-shrink: 0;
  text-align: right;
}

.price-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--ap-text);
  font-variant-numeric: tabular-nums;
}

.price-value small {
  margin-left: 2px;
  font-size: 11px;
  font-weight: 400;
  color: var(--ap-muted);
}

.price-change {
  margin-top: 1px;
  font-size: 11px;
  color: var(--ap-muted);
  font-variant-numeric: tabular-nums;
}

.list-card :deep(.van-list__finished-text) {
  font-size: 11px;
  color: var(--ap-muted);
}

.list-card :deep(.van-list__loading) {
  min-height: 28px;
}
</style>
