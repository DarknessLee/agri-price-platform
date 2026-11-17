<template>
  <div class="h5-page alerts-page">
    <div class="h5-hero alerts-hero">
      <h1>预警中心</h1>
      <p>价格异常与风险预警，及时查看并处置</p>
    </div>

    <div class="h5-kpi-grid alerts-stats">
      <div class="h5-kpi">
        <div class="h5-kpi-label">未处置预警</div>
        <div class="h5-kpi-value">{{ stats ? fmtInt(stats.open_count) : '-' }}<small>条</small></div>
        <div class="h5-kpi-hint">含待处理与处理中</div>
      </div>
      <div class="h5-kpi">
        <div class="h5-kpi-label">近 30 天预警</div>
        <div class="h5-kpi-value">{{ stats ? fmtInt(stats.total_30d) : '-' }}<small>条</small></div>
        <div class="h5-kpi-hint">近 30 天预警总数</div>
      </div>
      <div class="h5-kpi">
        <div class="h5-kpi-label">处置率</div>
        <div class="h5-kpi-value">{{ stats ? `${fmtNum(stats.recall_rate, 1)}%` : '-' }}</div>
        <div class="h5-kpi-hint">已处置预警占比</div>
      </div>
      <div class="h5-kpi">
        <div class="h5-kpi-label">误报率</div>
        <div class="h5-kpi-value">{{ stats ? `${fmtNum(stats.false_positive_rate, 1)}%` : '-' }}</div>
        <div class="h5-kpi-hint">近 30 天误报占比</div>
      </div>
    </div>

    <div class="alerts-board">
      <Tabs v-model:active="activeStatus" shrink class="alerts-tabs" @change="onStatusChange">
        <Tab v-for="item in statusOptions" :key="item.value || 'all'" :title="item.title" />
      </Tabs>

      <div class="alert-level-row">
        <button
          v-for="item in levelOptions"
          :key="item.value || 'all'"
          type="button"
          class="level-chip"
          :class="{ 'level-chip-active': levelFilter === item.value }"
          @click="onLevelChange(item.value)"
        >
          {{ item.text }}
        </button>
      </div>

      <List
        v-model:loading="listLoading"
        :finished="listFinished"
        :finished-text="alerts.length ? '没有更多预警了' : ''"
        :immediate-check="true"
        @load="loadMore"
      >
        <div v-for="item in alerts" :key="item.id" class="alert-item" @click="openDetail(item)">
          <div class="alert-item-top">
            <Tag :type="levelTag(item.level)" plain>{{ item.level }}</Tag>
            <span class="alert-item-title">{{ item.title }}</span>
          </div>
          <div class="alert-item-meta">
            <span>{{ fmtDate(item.alert_date) }}</span>
            <span v-if="item.variety || item.region">{{ item.variety || '-' }} · {{ item.region || '-' }}</span>
          </div>
          <div class="alert-item-bottom">
            <span :class="['alert-status', `alert-status-${statusKey(item.status)}`]">
              {{ alertStatusText(item.status) }}
            </span>
            <span class="alert-view">查看详情 ›</span>
          </div>
        </div>
        <Empty v-if="listFinished && !alerts.length" description="暂无预警" :image-size="72" />
      </List>
    </div>

    <Popup v-model:show="detailVisible" position="bottom" round closeable :style="{ maxHeight: '80vh' }">
      <div v-if="detailRow" class="alert-detail">
        <div class="alert-detail-head">
          <Tag :type="levelTag(detailRow.level)" plain>{{ detailRow.level }}</Tag>
          <span class="alert-detail-title">{{ detailRow.title }}</span>
        </div>
        <div class="alert-detail-meta">
          <span>预警日期：{{ fmtDate(detailRow.alert_date) }}</span>
          <span :class="['alert-status', `alert-status-${statusKey(detailRow.status)}`]">
            {{ alertStatusText(detailRow.status) }}
          </span>
        </div>
        <CellGroup :border="false" class="alert-detail-cells">
          <Cell title="品种" :value="detailRow.variety || '-'" />
          <Cell title="地区" :value="detailRow.region || '-'" />
          <Cell v-if="detailRow.handler" title="处置人" :value="detailRow.handler" />
          <Cell v-if="detailRow.handled_at" title="处置时间" :value="fmtDateTime(detailRow.handled_at)" />
        </CellGroup>
        <div v-if="detailRow.detail" class="alert-detail-block">
          <div class="alert-detail-label">预警说明</div>
          <p class="alert-detail-text">{{ detailRow.detail }}</p>
        </div>
        <div v-if="detailRow.handle_note" class="alert-detail-block">
          <div class="alert-detail-label">处置说明</div>
          <p class="alert-detail-text">{{ detailRow.handle_note }}</p>
        </div>
        <div v-if="detailRow.status !== '已关闭'" class="alert-detail-actions">
          <template v-if="canHandle">
            <Button type="primary" block round :loading="submitting" @click="startHandle('ack')">确认处理</Button>
            <Button
              class="alert-close-btn"
              type="danger"
              plain
              block
              round
              :loading="submitting"
              @click="startHandle('close')"
            >
              关闭预警
            </Button>
          </template>
          <div v-else class="alert-no-perm">您没有处置权限</div>
        </div>
        <div v-else class="alert-closed-tip">该预警已关闭</div>
      </div>
    </Popup>

    <Dialog
      v-model:show="handleVisible"
      :title="handleMode === 'ack' ? '确认处理' : '关闭预警'"
      show-cancel-button
      confirm-button-text="提交"
      :before-close="onHandleClose"
    >
      <div class="handle-form">
        <Field
          v-model="handleNote"
          type="textarea"
          rows="3"
          :maxlength="200"
          show-word-limit
          label="处置说明"
          placeholder="请填写处置说明（必填）"
        />
        <Field
          v-if="handleMode === 'close'"
          v-model="handleResult"
          type="textarea"
          rows="3"
          :maxlength="200"
          show-word-limit
          label="处置结果"
          placeholder="请填写处置结果（必填）"
        />
      </div>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import {
  Button,
  Cell,
  CellGroup,
  Dialog,
  Empty,
  Field,
  List,
  Popup,
  Tab,
  Tabs,
  Tag,
  showToast,
} from 'vant';

import { alertApi } from '@/api';
import { useAuthStore } from '@/stores/auth';
import { alertStatusText, fmtDate, fmtDateTime, fmtInt, fmtNum, levelTag } from '@/utils/format';
import type { AlertRow, AlertStatistics } from '@/types';

const PAGE_SIZE = 15;

const statusOptions = [
  { title: '全部', value: '' },
  { title: '待处理', value: '待处理' },
  { title: '处理中', value: '处理中' },
  { title: '已关闭', value: '已关闭' },
];

const levelOptions = [
  { text: '全部', value: '' },
  { text: '高', value: '高' },
  { text: '中', value: '中' },
  { text: '低', value: '低' },
];

const auth = useAuthStore();
const canHandle = computed(() => auth.hasPerm('alert:handle'));

const stats = ref<AlertStatistics | null>(null);
const activeStatus = ref(0);
const levelFilter = ref('');

const alerts = ref<AlertRow[]>([]);
const page = ref(1);
const listLoading = ref(false);
const listFinished = ref(false);
const requesting = ref(false);

const detailVisible = ref(false);
const detailRow = ref<AlertRow | null>(null);
const handleVisible = ref(false);
const handleMode = ref<'ack' | 'close'>('ack');
const handleNote = ref('');
const handleResult = ref('');
const submitting = ref(false);

const currentStatus = computed(() => statusOptions[activeStatus.value]?.value || '');

async function loadStats(): Promise<void> {
  try {
    stats.value = await alertApi.statistics();
  } catch {
    showToast('数据服务暂不可用');
  }
}

function statusKey(status: string): string {
  if (status === '待处理') return 'open';
  if (status === '处理中') return 'doing';
  if (status === '已关闭') return 'closed';
  return 'default';
}

async function loadMore(): Promise<void> {
  if (requesting.value || listFinished.value) {
    listLoading.value = false;
    return;
  }
  requesting.value = true;
  listLoading.value = true;
  try {
    const data = await alertApi.list({
      status: currentStatus.value || undefined,
      level: levelFilter.value || undefined,
      page: page.value,
      page_size: PAGE_SIZE,
    });
    const list = data.list || [];
    alerts.value = page.value === 1 ? list : alerts.value.concat(list);
    const total = Number(data.total || 0);
    listFinished.value = total > 0 ? alerts.value.length >= total : list.length < PAGE_SIZE;
    page.value += 1;
  } catch {
    showToast('数据服务暂不可用');
  } finally {
    requesting.value = false;
    listLoading.value = false;
  }
}

function resetList(): void {
  alerts.value = [];
  page.value = 1;
  listFinished.value = false;
  listLoading.value = false;
  void loadMore();
}

function onStatusChange(): void {
  resetList();
}

function onLevelChange(value: string): void {
  if (levelFilter.value === value) return;
  levelFilter.value = value;
  resetList();
}

async function openDetail(row: AlertRow): Promise<void> {
  detailRow.value = row;
  detailVisible.value = true;
  try {
    const detail = await alertApi.detail(row.id);
    if (detail) detailRow.value = detail;
  } catch {
    showToast('数据服务暂不可用');
  }
}

function startHandle(mode: 'ack' | 'close'): void {
  if (!detailRow.value || submitting.value) return;
  handleMode.value = mode;
  handleNote.value = '';
  handleResult.value = '';
  handleVisible.value = true;
}

async function onHandleClose(action: string): Promise<boolean> {
  if (action !== 'confirm') return true;
  const row = detailRow.value;
  if (!row) return false;
  if (!handleNote.value.trim()) {
    showToast('请填写处置说明');
    return false;
  }
  if (handleMode.value === 'close' && !handleResult.value.trim()) {
    showToast('请填写处置结果');
    return false;
  }
  if (submitting.value) return false;
  submitting.value = true;
  try {
    if (handleMode.value === 'ack') {
      await alertApi.ack(row.id, handleNote.value.trim());
      showToast('已确认处理');
    } else {
      await alertApi.close(row.id, handleNote.value.trim(), handleResult.value.trim());
      showToast('预警已关闭');
    }
    detailVisible.value = false;
    resetList();
    void loadStats();
    return true;
  } catch {
    showToast('数据服务暂不可用');
    return false;
  } finally {
    submitting.value = false;
  }
}

onMounted(() => {
  void loadStats();
});
</script>

<style scoped>
.alerts-hero {
  padding-bottom: 20px;
}

.alerts-stats {
  margin-bottom: 12px;
}

.alerts-board {
  padding: 0 12px 8px;
  border-radius: 12px;
  background: var(--ap-card);
  box-shadow: 0 1px 3px rgba(18, 35, 63, 0.06);
}

.alerts-tabs {
  margin: 0 -12px;
}

.alert-level-row {
  display: flex;
  gap: 8px;
  padding: 10px 0 6px;
  border-bottom: 1px solid var(--ap-border);
}

.level-chip {
  padding: 3px 14px;
  border: 1px solid var(--ap-border);
  border-radius: 14px;
  background: #fff;
  color: var(--ap-text-2);
  font-size: 12px;
  line-height: 20px;
}

.level-chip-active {
  border-color: var(--ap-primary);
  background: #eef3fd;
  color: var(--ap-primary);
  font-weight: 500;
}

.alert-item {
  padding: 12px 0;
  border-bottom: 1px solid var(--ap-border);
}

.alert-item:last-child {
  border-bottom: none;
}

.alert-item-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.alert-item-title {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  font-weight: 500;
  color: var(--ap-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.alert-item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--ap-muted);
}

.alert-item-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}

.alert-view {
  font-size: 12px;
  color: var(--ap-primary);
}

.alert-status {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  line-height: 18px;
}

.alert-status-open {
  background: #fdecec;
  color: #d64545;
}

.alert-status-doing {
  background: #fdf3e4;
  color: #e08b1f;
}

.alert-status-closed {
  background: #e8f5ee;
  color: #1f9d63;
}

.alert-status-default {
  background: #eef1f6;
  color: var(--ap-muted);
}

.alert-detail {
  padding: 18px 16px calc(18px + env(safe-area-inset-bottom));
}

.alert-detail-head {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding-right: 22px;
}

.alert-detail-title {
  flex: 1;
  min-width: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--ap-text);
  word-break: break-all;
}

.alert-detail-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 8px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--ap-border);
  font-size: 12px;
  color: var(--ap-muted);
}

.alert-detail-cells {
  margin: 4px -16px 0;
}

.alert-detail-block {
  margin-top: 12px;
}

.alert-detail-label {
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ap-text-2);
}

.alert-detail-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--ap-text);
  word-break: break-all;
}

.alert-detail-actions {
  margin-top: 18px;
}

.alert-close-btn {
  margin-top: 10px;
}

.alert-no-perm {
  padding: 10px;
  border-radius: 8px;
  background: #f4f6fa;
  font-size: 12px;
  color: var(--ap-muted);
  text-align: center;
}

.alert-closed-tip {
  margin-top: 16px;
  font-size: 12px;
  color: var(--ap-muted);
  text-align: center;
}

.handle-form {
  padding: 4px 0;
}
</style>
