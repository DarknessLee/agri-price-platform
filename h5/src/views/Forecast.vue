<template>
  <div class="h5-page">
    <div class="h5-hero">
      <h1>价格预测</h1>
      <p>基于历史价格与季节因子生成未来走势，仅供参考</p>
    </div>

    <div class="h5-card">
      <div class="h5-card-title">
        <span>预测条件</span>
      </div>

      <VanTabs v-model:active="varietyIndex" class="variety-tabs" shrink swipe-threshold="3">
        <VanTab v-for="item in varieties" :key="item.id" :title="item.name" />
      </VanTabs>

      <div class="field-label">地区</div>
      <div class="region-chips">
        <button
          v-for="item in regions"
          :key="item.id"
          type="button"
          class="region-chip"
          :class="{ active: regionId === item.id }"
          @click="regionId = item.id"
        >
          {{ item.name }}
        </button>
      </div>

      <div class="filter-line">
        <span class="filter-label">预测天数</span>
        <div class="seg">
          <button
            v-for="item in horizons"
            :key="item"
            type="button"
            class="seg-btn"
            :class="{ active: horizon === item }"
            @click="horizon = item"
          >
            {{ item }} 天
          </button>
        </div>
      </div>

      <VanButton
        class="run-btn"
        type="primary"
        block
        round
        :loading="running"
        :disabled="!varietyId || !regionId"
        loading-text="预测计算中"
        @click="runForecast"
      >
        开始预测
      </VanButton>
    </div>

    <template v-if="result">
      <div ref="resultAnchor" class="conclusion">
        <div class="conclusion-head">
          <div>
            <div class="conclusion-label">预计变动幅度</div>
            <div class="conclusion-value" :class="changeTone">{{ fmtPct(expectedChange) }}</div>
            <div class="conclusion-sub">未来 {{ forecastDays }} 天 · 目标 {{ lastPoint ? fmtDate(lastPoint.target_date) : '-' }}</div>
          </div>
          <div class="conclusion-tags">
            <span class="c-tag">趋势 {{ summary.trend }}</span>
            <span class="c-tag">风险 {{ summary.risk_level }}</span>
            <span class="c-tag">置信度 {{ summary.confidence_level }}</span>
          </div>
        </div>
        <p class="conclusion-text">{{ summary.text }}</p>
      </div>

      <div class="h5-card">
        <div class="h5-row">
          <span class="h5-row-label">预测模型</span>
          <span class="h5-row-value">{{ model.name || '-' }}</span>
        </div>
        <div class="h5-row">
          <span class="h5-row-label">回测 MAPE</span>
          <span class="h5-row-value">{{ fmtNum(model.mape) }}%</span>
        </div>
        <div class="h5-row">
          <span class="h5-row-label">方向准确率</span>
          <span class="h5-row-value">{{ fmtNum(model.direction_acc, 1) }}%</span>
        </div>
        <div class="h5-row">
          <span class="h5-row-label">区间置信度</span>
          <span class="h5-row-value">{{ confidenceText }}</span>
        </div>
      </div>

      <div class="h5-card chart-card">
        <div class="h5-card-title">
          <span>走势对照</span>
          <span class="h5-muted">历史 + 预测 {{ forecastDays }} 天 · {{ unit }}</span>
        </div>
        <AppChart :option="chartOption" :height="230" />
        <div class="legend">
          <span class="legend-item"><i class="dot history" />历史价格</span>
          <span class="legend-item"><i class="dot forecast" />预测价格</span>
          <span class="legend-item"><i class="dot band" />置信区间</span>
        </div>
      </div>

      <VanCollapse v-model="detailActive" class="detail-collapse">
        <VanCollapseItem :title="`逐日预测明细（${forecastDays} 天）`" name="detail">
          <div class="forecast-list">
            <div v-for="item in result.forecast" :key="item.target_date" class="forecast-item">
              <span class="forecast-date">{{ fmtDate(item.target_date) }}</span>
              <span class="forecast-point">{{ fmtNum(item.point) }}<small>{{ unit }}</small></span>
              <span class="forecast-range">{{ fmtNum(item.lower) }} ~ {{ fmtNum(item.upper) }}</span>
              <span class="forecast-dir" :class="dirClass(item.direction)">{{ item.direction }}</span>
            </div>
          </div>
        </VanCollapseItem>
      </VanCollapse>

      <div v-if="explains.length" class="h5-card">
        <div class="h5-card-title">
          <span>影响因素</span>
        </div>
        <div v-for="item in explains" :key="item.factor" class="h5-row">
          <span class="h5-row-label">{{ item.factor }}</span>
          <span class="h5-row-value">{{ fmtNum(item.contribution, 1) }}%</span>
        </div>
      </div>
    </template>

    <div v-else class="h5-card guide-card">
      <VanEmpty description="选择品种、地区与天数后点击开始预测" image="search" />
    </div>

    <div class="h5-card">
      <div class="h5-card-title">
        <span>最近预测记录</span>
        <span v-if="recent.length" class="h5-muted">点击可回看</span>
      </div>
      <div v-if="recentLoading" class="h5-empty">加载中...</div>
      <template v-else-if="recent.length">
        <div v-for="item in recent" :key="item.id" class="recent-item" @click="replay(item)">
          <div class="recent-main">
            <div class="recent-title">{{ item.variety || '-' }} · {{ item.region || '-' }}</div>
            <div class="recent-sub">
              {{ item.horizon || '-' }} 天 · {{ item.model || '-' }} · {{ item.created_at ? fmtDate(item.created_at) : '-' }}
            </div>
          </div>
          <div class="recent-side">
            <span :class="trendClass(item.expected_change_pct)">{{ fmtPct(item.expected_change_pct) }}</span>
            <span class="recent-mape">MAPE {{ fmtNum(item.mape) }}%</span>
          </div>
        </div>
      </template>
      <VanEmpty v-else description="暂无预测记录" :image-size="60" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import {
  Button as VanButton,
  Collapse as VanCollapse,
  CollapseItem as VanCollapseItem,
  Empty as VanEmpty,
  Tab as VanTab,
  Tabs as VanTabs,
  showFailToast,
  showToast,
} from 'vant';

import { ApiError } from '@/api/client';
import { forecastApi, metaApi } from '@/api';
import AppChart from '@/components/AppChart.vue';
import type { DictOption, ForecastPoint, ForecastResult, MetaDicts } from '@/types';
import { fmtDate, fmtNum, fmtPct, shortDate, trendClass } from '@/utils/format';

interface RecentForecast {
  id: number;
  variety_id?: number;
  variety?: string;
  region_id?: number;
  region?: string;
  horizon?: number;
  model?: string;
  mape?: number;
  expected_change_pct?: number;
  direction?: string;
  created_at?: string;
}

const horizons = [7, 14, 30];

const dicts = ref<MetaDicts | null>(null);
const ready = ref(false);
const varietyIndex = ref(0);
const regionId = ref<number | null>(null);
const horizon = ref(14);

const running = ref(false);
const result = ref<ForecastResult | null>(null);
const detailActive = ref<string[]>([]);
const resultAnchor = ref<HTMLDivElement | null>(null);

const recent = ref<RecentForecast[]>([]);
const recentLoading = ref(false);

const varieties = computed<DictOption[]>(() => dicts.value?.varieties || []);
const regions = computed<DictOption[]>(() => dicts.value?.regions || []);
const varietyId = computed<number | undefined>(() => varieties.value[varietyIndex.value]?.id);

const unit = computed<string>(() => result.value?.unit || '元/公斤');
const summary = computed(() => result.value?.summary || { expected_change_pct: 0, trend: '-', risk_level: '-', confidence_level: '-', text: '' });
const model = computed(() => result.value?.model || { key: '', name: '', mape: 0, direction_acc: 0 });
const expectedChange = computed<number | null>(() => {
  const value = summary.value.expected_change_pct;
  return typeof value === 'number' ? value : null;
});
const forecastDays = computed(() => result.value?.forecast?.length || 0);
const lastPoint = computed<ForecastPoint | null>(() => {
  const list = result.value?.forecast || [];
  return list.length ? list[list.length - 1] : null;
});
const confidenceText = computed(() => {
  const value = lastPoint.value?.confidence;
  return typeof value === 'number' ? `${fmtNum(value * 100, 0)}%` : '-';
});
const explains = computed(() => (result.value?.explain || []).slice(0, 5));
const changeTone = computed(() => {
  const value = expectedChange.value;
  if (value === null) return '';
  return value > 0 ? 'rise' : value < 0 ? 'fall' : '';
});

function hexToRgba(hex: string, alpha: number): string {
  const value = hex.replace('#', '');
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const chartOption = computed<Record<string, unknown>>(() => {
  const data = result.value;
  if (!data) return {};
  const histDates = data.history?.dates || [];
  const histValues = data.history?.values || [];
  const points = data.forecast || [];
  const unitText = unit.value;

  const dates = [...histDates, ...points.map((item) => item.target_date)];
  const historyLen = histValues.length;
  const nullTail = (): Array<number | null> => histValues.map(() => null);

  const historyLine: Array<number | null> = [...histValues, ...points.map(() => null)];
  const forecastLine: Array<number | null> = histValues.map((value, index) =>
    index === historyLen - 1 ? value : null,
  );
  forecastLine.push(...points.map((item) => item.point));

  const lowerLine = nullTail();
  lowerLine.push(...points.map((item) => item.lower));
  const bandLine = nullTail();
  bandLine.push(...points.map((item) => Math.max(0, item.upper - item.lower)));

  const pointByIndex = new Map<number, ForecastPoint>();
  points.forEach((item, index) => pointByIndex.set(historyLen + index, item));

  return {
    grid: { left: 4, right: 10, top: 16, bottom: 0, containLabel: true },
    tooltip: {
      trigger: 'axis',
      confine: true,
      formatter: (params: unknown) => {
        const list = (Array.isArray(params) ? params : [params]) as Array<{ dataIndex?: number }>;
        const index = Number(list[0]?.dataIndex ?? 0);
        const lines: string[] = [`<div style="font-weight:600;margin-bottom:2px">${fmtDate(dates[index])}</div>`];
        const histValue = histValues[index];
        if (histValue !== undefined && histValue !== null) {
          lines.push(`历史价格：${fmtNum(histValue)} ${unitText}`);
        }
        const point = pointByIndex.get(index);
        if (point) {
          lines.push(`预测价格：${fmtNum(point.point)} ${unitText}`);
          lines.push(`置信区间：${fmtNum(point.lower)} ~ ${fmtNum(point.upper)}`);
        }
        return lines.join('<br/>');
      },
    },
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
        formatter: (value: string) => shortDate(value),
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
    series: [
      {
        name: '区间下界',
        type: 'line',
        data: lowerLine,
        stack: 'band',
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { opacity: 0 },
        silent: true,
        z: 1,
      },
      {
        name: '区间上界',
        type: 'line',
        data: bandLine,
        stack: 'band',
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: hexToRgba('#1f5fd6', 0.14) },
        silent: true,
        z: 1,
      },
      {
        name: '历史价格',
        type: 'line',
        data: historyLine,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#1f5fd6' },
        itemStyle: { color: '#1f5fd6' },
        z: 3,
      },
      {
        name: '预测价格',
        type: 'line',
        data: forecastLine,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#e08b1f', type: 'dashed' },
        itemStyle: { color: '#e08b1f' },
        z: 4,
      },
    ],
  };
});

function dirClass(direction: string): string {
  if (direction === '上涨') return 'h5-up';
  if (direction === '下跌') return 'h5-down';
  return 'h5-muted';
}

function showError(error: unknown, fallback: string = '数据服务暂不可用'): void {
  const message = error instanceof ApiError && error.message ? error.message : fallback;
  showFailToast(message);
}

async function loadDicts(): Promise<void> {
  try {
    dicts.value = await metaApi.dicts();
    if (!regionId.value && regions.value.length) {
      regionId.value = regions.value[0].id;
    }
  } catch (error) {
    showError(error, '基础数据加载失败');
  }
}

async function loadRecent(): Promise<void> {
  recentLoading.value = true;
  try {
    const data = await forecastApi.results({
      variety_id: varietyId.value,
      region_id: regionId.value || undefined,
      limit: 5,
    });
    recent.value = (data as unknown as RecentForecast[]) || [];
  } catch (error) {
    recent.value = [];
    showError(error, '预测记录加载失败');
  } finally {
    recentLoading.value = false;
  }
}

async function runForecast(): Promise<void> {
  if (!varietyId.value) {
    showFailToast('请选择品种');
    return;
  }
  if (!regionId.value) {
    showFailToast('请选择地区');
    return;
  }
  running.value = true;
  const started = Date.now();
  try {
    const data = await forecastApi.run({
      variety_id: varietyId.value,
      region_id: regionId.value,
      horizon: horizon.value,
    });
    const elapsed = Date.now() - started;
    if (elapsed < 1200) {
      await new Promise<void>((resolve) => setTimeout(resolve, 1200 - elapsed));
    }
    result.value = data;
    detailActive.value = [];
    showToast('预测完成');
    void loadRecent();
    await nextTick();
    resultAnchor.value?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    showError(error, '预测服务暂不可用');
  } finally {
    running.value = false;
  }
}

async function replay(item: RecentForecast): Promise<void> {
  if (!item.variety_id || !item.region_id) {
    showFailToast('该记录缺少品种或地区信息');
    return;
  }
  const index = varieties.value.findIndex((variety) => variety.id === item.variety_id);
  if (index >= 0) varietyIndex.value = index;
  regionId.value = item.region_id;
  if (item.horizon && horizons.includes(item.horizon)) horizon.value = item.horizon;
  await nextTick();
  await runForecast();
}

watch([varietyId, regionId], () => {
  if (!ready.value) return;
  void loadRecent();
});

onMounted(async () => {
  await loadDicts();
  ready.value = true;
  void loadRecent();
});
</script>

<style scoped>
.variety-tabs {
  margin-bottom: 4px;
}

.variety-tabs :deep(.van-tab) {
  padding: 0 12px;
  font-size: 13px;
}

.variety-tabs :deep(.van-tabs__line) {
  width: 22px;
  border-radius: 2px;
}

.field-label {
  margin: 8px 0 6px;
  font-size: 12px;
  color: var(--ap-muted);
}

.region-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.region-chip {
  height: 28px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 14px;
  background: #f1f4f9;
  color: var(--ap-text-2);
  font-size: 12px;
  line-height: 26px;
}

.region-chip.active {
  border-color: var(--ap-primary);
  background: #eaf1fd;
  color: var(--ap-primary);
  font-weight: 600;
}

.filter-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px 0 14px;
}

.filter-label {
  flex-shrink: 0;
  width: 52px;
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

.run-btn {
  margin-top: 14px;
}

.guide-card {
  padding: 4px 0;
}

.conclusion {
  margin-bottom: 12px;
  padding: 16px;
  border-radius: 14px;
  color: #fff;
  background: linear-gradient(140deg, #12233f 0%, #1a3a6d 52%, #1f5fd6 100%);
  box-shadow: 0 4px 14px rgba(18, 35, 63, 0.18);
}

.conclusion-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.conclusion-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}

.conclusion-value {
  margin: 2px 0;
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  font-variant-numeric: tabular-nums;
}

.conclusion-value.rise {
  color: #ffb3a7;
}

.conclusion-value.fall {
  color: #7ee2b8;
}

.conclusion-sub {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.62);
}

.conclusion-tags {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}

.c-tag {
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.14);
  font-size: 11px;
  color: rgba(255, 255, 255, 0.9);
  text-align: center;
}

.conclusion-text {
  margin: 12px 0 0;
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.14);
  font-size: 12px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.82);
}

.chart-card {
  padding-bottom: 6px;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  padding: 2px 2px 4px;
  font-size: 11px;
  color: var(--ap-text-2);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.dot {
  width: 10px;
  height: 3px;
  border-radius: 2px;
}

.dot.history {
  background: #1f5fd6;
}

.dot.forecast {
  background: #e08b1f;
}

.dot.band {
  height: 8px;
  border-radius: 2px;
  background: rgba(31, 95, 214, 0.18);
}

.detail-collapse :deep(.van-collapse-item__title) {
  font-size: 13px;
  font-weight: 600;
}

.detail-collapse :deep(.van-cell) {
  padding: 12px 0;
}

.detail-collapse :deep(.van-cell__title) {
  font-size: 13px;
}

.forecast-list {
  margin: 0 -4px;
}

.forecast-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 4px;
  border-bottom: 1px solid var(--ap-border);
  font-size: 12px;
}

.forecast-item:last-child {
  border-bottom: none;
}

.forecast-date {
  width: 74px;
  flex-shrink: 0;
  color: var(--ap-text);
}

.forecast-point {
  flex-shrink: 0;
  font-weight: 600;
  color: var(--ap-primary);
  font-variant-numeric: tabular-nums;
}

.forecast-point small {
  margin-left: 2px;
  font-size: 10px;
  font-weight: 400;
  color: var(--ap-muted);
}

.forecast-range {
  flex: 1;
  min-width: 0;
  color: var(--ap-muted);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.forecast-dir {
  width: 34px;
  flex-shrink: 0;
  text-align: right;
}

.recent-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px solid var(--ap-border);
}

.recent-item:last-child {
  border-bottom: none;
}

.recent-main {
  flex: 1;
  min-width: 0;
}

.recent-title {
  overflow: hidden;
  font-size: 13px;
  font-weight: 500;
  color: var(--ap-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-sub {
  margin-top: 2px;
  overflow: hidden;
  font-size: 11px;
  color: var(--ap-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  flex-shrink: 0;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.recent-mape {
  margin-top: 1px;
  font-size: 11px;
  color: var(--ap-muted);
}
</style>
