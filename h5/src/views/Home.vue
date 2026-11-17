<template>
  <VanPullRefresh v-model="refreshing" class="home-pull" @refresh="onRefresh">
    <div class="h5-page home-page">
      <section class="h5-hero home-hero">
        <div class="hero-top">
          <div class="hero-main">
            <p class="hero-greet">{{ greeting }}，{{ displayName }}</p>
            <p class="hero-sub">{{ roleName }} · {{ todayText }} {{ weekdayText }}</p>
          </div>
          <button type="button" class="hero-bell" aria-label="通知" @click="onBellClick">
            <VanBadge :content="unread" :hidden="unread <= 0" :max="99">
              <VanIcon name="bell" size="20" color="#ffffff" />
            </VanBadge>
          </button>
        </div>
        <div class="hero-meta">
          <span>数据更新至 {{ latestDateText }}</span>
          <span class="hero-dot">·</span>
          <span>{{ varietyCountText }} 个品种</span>
          <span class="hero-dot">·</span>
          <span>{{ marketCountText }} 个市场</span>
        </div>
      </section>

      <section class="h5-kpi-grid">
        <StatCard
          label="平均价格"
          :value="avgPriceText"
          unit="元/公斤"
          :hint="yoyHint"
          :hint-class="trendClass(kpi?.yoy_pct)"
          tone="blue"
        />
        <StatCard
          label="数据记录"
          :value="recordText"
          unit="条"
          :hint="recordHint"
          tone="green"
        />
        <StatCard
          label="未处置预警"
          :value="alertOpenText"
          unit="条"
          :hint="alertHint"
          tone="orange"
        />
        <StatCard
          label="方向准确率"
          :value="directionText"
          unit="%"
          :hint="mapeHint"
          tone="red"
        />
      </section>

      <section class="h5-card quick-card">
        <div class="h5-card-title">
          <span>快捷入口</span>
          <span class="h5-muted">常用功能</span>
        </div>
        <VanGrid :column-num="4" :border="false" :gutter="6" class="quick-grid">
          <VanGridItem
            v-for="item in QUICK_LINKS"
            :key="item.path"
            :icon="item.icon"
            :text="item.text"
            @click="router.push(item.path)"
          />
        </VanGrid>
      </section>

      <section class="h5-card trend-card">
        <div class="h5-card-title">
          <span>价格走势</span>
          <span class="trend-latest">
            {{ latestPriceText }}<small>{{ trendUnit }}</small>
          </span>
        </div>
        <VanTabs
          v-model:active="activeVariety"
          class="variety-tabs"
          shrink
          :duration="0.2"
          @change="onVarietyChange"
        >
          <VanTab v-for="(item, index) in varieties" :key="item.id" :name="index" :title="item.name" />
        </VanTabs>
        <p v-if="!varieties.length" class="h5-muted trend-tip">行情品种加载中，先展示综合均价走势</p>
        <AppChart
          :option="trendOption"
          :height="180"
          :empty="!trendHasData"
          :empty-text="loading ? '走势加载中…' : '暂无走势数据'"
        />
        <div class="trend-foot">
          <span class="h5-muted">近 90 天 · 单位 {{ trendUnit }}</span>
          <button type="button" class="trend-more" @click="router.push('/prices')">查看行情</button>
        </div>
      </section>

      <section class="h5-card alert-card">
        <div class="h5-card-title">
          <span>最新预警</span>
          <button type="button" class="alert-more" @click="router.push('/alerts')">全部预警</button>
        </div>
        <div v-if="alerts.length" class="alert-list">
          <button
            v-for="item in alerts"
            :key="item.id"
            type="button"
            class="alert-row"
            @click="router.push('/alerts')"
          >
            <VanTag :type="levelTag(item.level)" plain size="medium" class="alert-tag">
              {{ item.level }}
            </VanTag>
            <span class="alert-main">
              <span class="alert-title">{{ item.title }}</span>
              <span class="alert-meta">
                {{ item.variety || '全部品种' }} · {{ item.region || '全部地区' }}
              </span>
            </span>
            <span class="alert-date">{{ shortDate(item.alert_date) }}</span>
          </button>
        </div>
        <div v-else class="h5-empty">{{ loading ? '预警加载中…' : '暂无未处置预警' }}</div>
      </section>

      <p class="home-foot">下拉可刷新数据 · 移动端仅提供查询与处置</p>
    </div>
  </VanPullRefresh>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  Badge as VanBadge,
  Grid as VanGrid,
  GridItem as VanGridItem,
  Icon as VanIcon,
  PullRefresh as VanPullRefresh,
  Tab as VanTab,
  Tabs as VanTabs,
  Tag as VanTag,
  showFailToast,
  showToast,
} from 'vant';

import AppChart from '@/components/AppChart.vue';
import StatCard from '@/components/StatCard.vue';
import { dashboardApi, metaApi, notificationApi } from '@/api';
import { useAuthStore } from '@/stores/auth';
import {
  fmtDate,
  fmtInt,
  fmtNum,
  fmtPct,
  levelTag,
  shortDate,
  today,
  trendClass,
  weekday,
} from '@/utils/format';
import type { AlertRow, DashboardSummary, DictOption, TrendData } from '@/types';

const router = useRouter();
const auth = useAuthStore();

const QUICK_LINKS = [
  { path: '/prices', icon: 'chart-trending-o', text: '价格行情' },
  { path: '/forecast', icon: 'bar-chart-o', text: '价格预测' },
  { path: '/alerts', icon: 'warning-o', text: '预警处置' },
  { path: '/me', icon: 'user-o', text: '我的' },
];

const loading = ref(true);
const refreshing = ref(false);
const summary = ref<DashboardSummary | null>(null);
const varieties = ref<DictOption[]>([]);
const activeVariety = ref(0);
const trendData = ref<TrendData | null>(null);
const alerts = ref<AlertRow[]>([]);
const unread = ref(0);

const kpi = computed(() => summary.value?.kpi ?? null);

const displayName = computed(
  () => auth.user?.display_name || auth.user?.username || '用户',
);
const roleName = computed(() => auth.user?.role_name || '平台用户');

const greeting = computed(() => {
  const hour = new Date().getHours();
  if (hour < 12) return '早上好';
  if (hour < 18) return '下午好';
  return '晚上好';
});

const todayText = today();
const weekdayText = weekday();

const latestDateText = computed(() => fmtDate(summary.value?.latest_price_date));
const varietyCountText = computed(() => (kpi.value ? fmtInt(kpi.value.variety_count) : '-'));
const marketCountText = computed(() => (kpi.value ? fmtInt(kpi.value.market_count) : '-'));

const avgPriceText = computed(() => (kpi.value ? fmtNum(kpi.value.avg_price, 2) : '-'));
const yoyHint = computed(() => (kpi.value ? `同比 ${fmtPct(kpi.value.yoy_pct)}` : '同比 -'));
const recordText = computed(() => (kpi.value ? fmtInt(kpi.value.record_count) : '-'));
const recordHint = computed(() =>
  kpi.value ? `覆盖 ${fmtInt(kpi.value.variety_count)} 品种 / ${fmtInt(kpi.value.market_count)} 市场` : '累计入库记录',
);
const alertOpenText = computed(() => (kpi.value ? fmtInt(kpi.value.alert_open) : '-'));
const alertHint = computed(() => (kpi.value ? `今日新增 ${fmtInt(kpi.value.alert_today)} 条` : '今日新增 -'));
const directionText = computed(() => (kpi.value ? fmtNum(kpi.value.direction_acc, 1) : '-'));
const mapeHint = computed(() => (kpi.value ? `MAPE ${fmtNum(kpi.value.avg_mape, 1)}%` : 'MAPE -'));

const trendUnit = computed(() => trendData.value?.unit || '元/公斤');

const trendSeriesValues = computed<number[]>(() => {
  const values = trendData.value?.series?.[0]?.values;
  return Array.isArray(values) ? values : [];
});

const trendHasData = computed(() =>
  trendSeriesValues.value.some((value) => typeof value === 'number' && Number.isFinite(value)),
);

const latestPriceText = computed(() => {
  const values = trendSeriesValues.value;
  for (let index = values.length - 1; index >= 0; index -= 1) {
    const value = values[index];
    if (typeof value === 'number' && Number.isFinite(value)) return fmtNum(value, 2);
  }
  const fallback = trendData.value?.latest;
  return typeof fallback === 'number' ? fmtNum(fallback, 2) : '-';
});

const trendOption = computed<Record<string, unknown>>(() => ({
  animationDuration: 500,
  grid: { left: 6, right: 8, top: 14, bottom: 6 },
  tooltip: {
    trigger: 'axis',
    confine: true,
    backgroundColor: 'rgba(18, 35, 63, 0.92)',
    borderWidth: 0,
    padding: [6, 10],
    textStyle: { color: '#ffffff', fontSize: 12 },
    valueFormatter: (value: unknown) => `${fmtNum(Number(value), 2)} ${trendUnit.value}`,
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: (trendData.value?.dates || []).map((item) => shortDate(item)),
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { show: false },
    splitLine: { show: false },
  },
  yAxis: {
    type: 'value',
    scale: true,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { show: false },
    splitLine: { lineStyle: { color: '#eef2f8' } },
  },
  series: [
    {
      type: 'line',
      data: trendSeriesValues.value,
      smooth: true,
      showSymbol: false,
      connectNulls: true,
      lineStyle: { width: 2, color: '#1f5fd6' },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(31, 95, 214, 0.30)' },
            { offset: 1, color: 'rgba(31, 95, 214, 0.02)' },
          ],
        },
      },
    },
  ],
}));

async function loadSummary(): Promise<boolean> {
  try {
    summary.value = await dashboardApi.summary();
    return true;
  } catch {
    return false;
  }
}

async function loadMeta(): Promise<boolean> {
  try {
    const result = await metaApi.dicts();
    varieties.value = result.varieties || [];
    if (activeVariety.value >= varieties.value.length) activeVariety.value = 0;
    return true;
  } catch {
    return false;
  }
}

async function loadTrend(): Promise<boolean> {
  const variety = varieties.value[activeVariety.value];
  try {
    trendData.value = await dashboardApi.trend({ variety_id: variety?.id, days: 90 });
    return true;
  } catch {
    trendData.value = null;
    return false;
  }
}

async function loadAlerts(): Promise<boolean> {
  try {
    alerts.value = (await dashboardApi.alerts(3)) || [];
    return true;
  } catch {
    alerts.value = [];
    return false;
  }
}

async function loadUnread(): Promise<boolean> {
  try {
    const result = await notificationApi.summary();
    unread.value = Number(result?.unread) || 0;
    return true;
  } catch {
    unread.value = 0;
    return false;
  }
}

async function loadAll(reportError = false): Promise<void> {
  const results = await Promise.all([loadSummary(), loadMeta(), loadAlerts(), loadUnread()]);
  const trendOk = await loadTrend();
  const failedCount = results.filter((item) => !item).length + (trendOk ? 0 : 1);
  loading.value = false;
  if (reportError) {
    if (failedCount >= 5) showFailToast('数据服务暂不可用，请稍后重试');
    else if (failedCount > 0) showToast('部分数据暂不可用');
  }
}

function onVarietyChange(name: number | string): void {
  activeVariety.value = Number(name) || 0;
  void loadTrend();
}

function onBellClick(): void {
  showToast('请在电脑端查看完整通知');
}

async function onRefresh(): Promise<void> {
  try {
    await loadAll(true);
  } finally {
    refreshing.value = false;
  }
}

onMounted(() => {
  void loadAll(false);
});
</script>

<style scoped>
.home-pull {
  min-height: 100vh;
}

.home-page {
  overflow-x: hidden;
}

.home-hero {
  position: relative;
}

.hero-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.hero-main {
  flex: 1;
  min-width: 0;
}

.hero-greet {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  line-height: 1.4;
  color: #ffffff;
}

.hero-sub {
  margin: 5px 0 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.78);
}

.hero-bell {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border: 1px solid rgba(255, 255, 255, 0.22);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.12);
}

.hero-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 14px;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.72);
}

.hero-dot {
  opacity: 0.6;
}

.quick-card {
  padding-bottom: 8px;
}

.quick-grid :deep(.van-grid-item__content) {
  padding: 6px 0;
  background: transparent;
}

.quick-grid :deep(.van-grid-item__icon) {
  font-size: 20px;
  color: var(--ap-primary);
}

.quick-grid :deep(.van-grid-item__text) {
  margin-top: 4px;
  font-size: 12px;
  color: var(--ap-text-2);
}

.trend-card {
  padding-bottom: 10px;
}

.trend-latest {
  font-size: 17px;
  font-weight: 600;
  color: var(--ap-primary);
  font-variant-numeric: tabular-nums;
}

.trend-latest small {
  margin-left: 3px;
  font-size: 11px;
  font-weight: 400;
  color: var(--ap-muted);
}

.variety-tabs {
  margin: 0 -4px 6px;
}

.variety-tabs :deep(.van-tabs__wrap) {
  height: 34px;
}

.variety-tabs :deep(.van-tab) {
  padding: 0 12px;
  font-size: 13px;
  color: var(--ap-text-2);
}

.variety-tabs :deep(.van-tab--active) {
  font-weight: 600;
  color: var(--ap-primary);
}

.trend-tip {
  margin: 0 0 4px;
}

.trend-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
}

.trend-more {
  padding: 0;
  border: none;
  background: transparent;
  font-size: 12px;
  color: var(--ap-primary);
}

.alert-card {
  margin-bottom: 4px;
}

.alert-more {
  padding: 0;
  border: none;
  background: transparent;
  font-size: 12px;
  color: var(--ap-primary);
}

.alert-list {
  display: flex;
  flex-direction: column;
}

.alert-row {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 10px 0;
  border: none;
  border-bottom: 1px solid var(--ap-border);
  background: transparent;
  text-align: left;
}

.alert-row:last-child {
  border-bottom: none;
}

.alert-tag {
  flex: none;
  margin-right: 8px;
}

.alert-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.alert-title {
  overflow: hidden;
  font-size: 13px;
  color: var(--ap-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.alert-meta {
  margin-top: 2px;
  overflow: hidden;
  font-size: 11px;
  color: var(--ap-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.alert-date {
  flex: none;
  margin-left: 8px;
  font-size: 11px;
  color: var(--ap-muted);
  font-variant-numeric: tabular-nums;
}

.home-foot {
  margin: 10px 0 0;
  font-size: 11px;
  color: var(--ap-muted);
  text-align: center;
}
</style>
