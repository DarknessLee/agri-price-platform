<template>
  <div class="page monitor-page">
    <PageHeader title="系统监控" subtitle="服务状态、请求指标与结构化日志检索">
      <template #actions>
        <el-button :icon="Refresh" :loading="refreshing" @click="refreshAll()">刷新</el-button>
      </template>
    </PageHeader>

    <div class="kpi-grid metrics-grid">
      <KpiCard
        label="QPS"
        :value="summary ? fmtNum(summary.qps, 2) : '—'"
        unit="req/s"
        icon="Odometer"
        tone="blue"
        :hint="summary ? `统计窗口 ${summary.window_minutes} 分钟` : '等待指标数据'"
      />
      <KpiCard
        label="平均耗时"
        :value="summary ? fmtNum(summary.avg_ms, 1) : '—'"
        unit="ms"
        icon="Timer"
        tone="green"
        :hint="summary ? `P50 ${fmtNum(summary.p50_ms, 1)} ms` : '等待指标数据'"
      />
      <KpiCard
        label="P95 耗时"
        :value="summary ? fmtNum(summary.p95_ms, 1) : '—'"
        unit="ms"
        icon="Odometer"
        tone="orange"
        :hint="summary ? `P99 ${fmtNum(summary.p99_ms, 1)} ms` : '等待指标数据'"
      />
      <KpiCard
        label="错误率"
        :value="summary ? fmtPct(summary.error_rate, 2, false) : '—'"
        icon="Warning"
        tone="red"
        :hint="summary ? `错误 ${fmtInt(summary.errors)} 次` : '等待指标数据'"
      />
      <KpiCard
        label="缓存命中率"
        :value="summary ? fmtPct(summary.cache?.hit_rate, 1, false) : '—'"
        icon="Connection"
        tone="purple"
        :hint="summary ? `HIT ${fmtInt(summary.cache?.HIT)} · MISS ${fmtInt(summary.cache?.MISS)}` : '等待指标数据'"
      />
      <KpiCard
        label="近一小时请求数"
        :value="summary ? fmtInt(summary.total) : '—'"
        unit="次"
        icon="Tickets"
        tone="blue"
        :hint="summary ? `更新于 ${fmtDateTime(summary.updated_at)}` : '等待指标数据'"
      />
    </div>

    <div class="page-card">
      <div class="card-title">
        <span>分钟级请求时序</span>
        <span class="title-extra">
          <el-radio-group v-model="minutes" size="small" @change="onMinutesChange">
            <el-radio-button :value="30">30 分钟</el-radio-button>
            <el-radio-button :value="60">60 分钟</el-radio-button>
            <el-radio-button :value="120">120 分钟</el-radio-button>
          </el-radio-group>
          <span class="muted">QPS / 平均耗时双 Y 轴 · 错误率联动展示</span>
        </span>
      </div>
      <BaseChart
        :option="trendOption"
        :height="320"
        :loading="chartLoading"
        :empty="!timeseries.length"
        empty-text="暂无请求时序数据"
      />
    </div>

    <div class="page-card">
      <div class="card-title">
        <span>日志检索</span>
        <span v-if="logStats" class="log-stats muted">
          目录 {{ logStats.path || '—' }} · {{ logStats.files ?? 0 }} 个文件 ·
          {{ fmtBytes(logStats.total_bytes) }} / 上限 {{ fmtBytes(logStats.max_bytes) }} ·
          备份 {{ logStats.backup_count ?? 0 }} 个
        </span>
      </div>
      <div class="toolbar">
        <el-select v-model="logLevel" placeholder="全部级别" clearable style="width: 130px" @change="loadLogs()">
          <el-option label="全部级别" value="" />
          <el-option v-for="level in levelOptions" :key="level" :label="level" :value="level" />
        </el-select>
        <el-input
          v-model="logKeyword"
          placeholder="关键词（事件 / 路径 / 请求 ID）"
          clearable
          style="width: 250px"
          :prefix-icon="Search"
          @keyup.enter="loadLogs()"
        />
        <el-select v-model="logLimit" style="width: 112px" @change="loadLogs()">
          <el-option v-for="size in limitOptions" :key="size" :label="`${size} 条`" :value="size" />
        </el-select>
        <el-button type="primary" :icon="Search" :loading="logLoading" @click="loadLogs()">查询</el-button>
        <el-button :icon="Refresh" @click="resetLogs">重置</el-button>
        <span class="muted grow" style="text-align: right">共 {{ logs.length }} 条匹配记录</span>
      </div>
      <el-table v-loading="logLoading" :data="logs" stripe border size="small" max-height="430">
        <el-table-column type="expand" width="36">
          <template #default="{ row }">
            <div class="log-detail">
              <pre>{{ pretty(row) }}</pre>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="162">
          <template #default="{ row }">
            <span class="mono">{{ fmtDateTime(row.ts) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="级别" width="86" align="center">
          <template #default="{ row }">
            <el-tag :type="levelType(row.level)" size="small" effect="light">{{ row.level || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="event" label="事件" min-width="170" show-overflow-tooltip />
        <el-table-column label="方法" width="78">
          <template #default="{ row }">
            <span class="mono">{{ row.method || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="路径" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono">{{ row.path || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态码" width="86" align="center">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small" effect="plain">{{ row.status ?? '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="92" align="right">
          <template #default="{ row }">
            <span class="mono">{{ row.elapsed_ms != null ? `${fmtNum(row.elapsed_ms, 0)} ms` : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="请求 ID" width="172" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono muted">{{ row.request_id || '—' }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="logFailed ? '数据服务暂不可用' : '暂无日志记录'" />
        </template>
      </el-table>
    </div>

    <div class="page-card">
      <div class="card-title">
        <span>服务状态</span>
        <span class="status-actions">
          <el-button size="small" :icon="Message" :loading="mailLoading" @click="onSendTestMail">发送测试邮件</el-button>
          <el-button
            size="small"
            type="primary"
            plain
            :icon="AlarmClock"
            :loading="tickLoading"
            @click="onTickTasks"
          >
            立即检查到期任务
          </el-button>
        </span>
      </div>
      <div v-if="status" class="status-grid">
        <div v-for="item in statusItems" :key="item.label" class="status-item">
          <div class="status-head">
            <span class="status-label">
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
            </span>
            <el-tag :type="item.tagType" size="small" effect="light">{{ item.tagText }}</el-tag>
          </div>
          <div class="status-value">{{ item.value }}</div>
          <div class="status-extra" :title="item.extra">{{ item.extra }}</div>
        </div>
      </div>
      <el-empty v-else description="数据服务暂不可用" :image-size="70" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { AlarmClock, Message, Refresh, Search } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import KpiCard from '@/components/KpiCard.vue'
import BaseChart from '@/components/BaseChart.vue'
import {
  fetchLogs,
  fetchMetricsSummary,
  fetchMetricsTimeseries,
  fetchSystemStatus,
  sendTestMail,
  tickTasks,
  type LogEntry,
  type LogStats,
  type MetricsPoint,
  type MetricsSummary,
  type SystemStatus,
} from '@/api/observability'
import { fmtDateTime, fmtInt, fmtNum, fmtPct } from '@/utils/format'

interface StatusItem {
  label: string
  value: string
  extra: string
  tagText: string
  tagType: 'success' | 'warning' | 'info' | 'danger'
  icon: string
}

const summary = ref<MetricsSummary | null>(null)
const timeseries = ref<MetricsPoint[]>([])
const logs = ref<LogEntry[]>([])
const logStats = ref<LogStats | null>(null)
const status = ref<SystemStatus | null>(null)

const minutes = ref(60)
const refreshing = ref(false)
const chartLoading = ref(false)
const logLoading = ref(false)
const mailLoading = ref(false)
const tickLoading = ref(false)
const logFailed = ref(false)

const logLevel = ref('')
const logKeyword = ref('')
const logLimit = ref(100)
const levelOptions = ['DEBUG', 'INFO', 'WARN', 'ERROR']
const limitOptions = [50, 100, 200, 500]

const statusItems = computed<StatusItem[]>(() => {
  const data = status.value
  if (!data) return []
  const items: StatusItem[] = []
  const storage = data.storage || {}
  const storageTag = !storage.configured
    ? { text: '未配置', type: 'info' as const }
    : storage.degraded || storage.ok === false
      ? { text: '降级', type: 'warning' as const }
      : { text: '正常', type: 'success' as const }
  const scheduler = data.scheduler || {}
  const mail = data.mail || {}
  const logInfo = data.logs || {}

  items.push({
    label: '数据库',
    value: textOf(data.db),
    extra: '业务数据存储',
    tagText: healthText(data.db),
    tagType: healthType(data.db),
    icon: 'Coin',
  })
  items.push({
    label: '缓存',
    value: textOf(data.cache),
    extra: 'Redis 缓存服务',
    tagText: healthText(data.cache),
    tagType: healthType(data.cache),
    icon: 'Connection',
  })
  items.push({
    label: '对象存储',
    value: storage.backend || '—',
    extra: `桶 ${storage.bucket || '—'} · ${storage.endpoint || '—'}${storage.error ? ` · ${storage.error}` : ''}`,
    tagText: storageTag.text,
    tagType: storageTag.type,
    icon: 'Files',
  })
  items.push({
    label: '调度器',
    value: scheduler.enabled ? (scheduler.running ? '运行中' : '已启用 · 待命') : '已暂停',
    extra: `心跳 ${scheduler.tick_seconds ?? '—'} 秒 · 上次 ${fmtDateTime(scheduler.last_tick_at)}${
      scheduler.last_result ? ` · ${String(scheduler.last_result).slice(0, 40)}` : ''
    }`,
    tagText: scheduler.enabled ? (scheduler.running ? '正常' : '待命') : '已暂停',
    tagType: scheduler.enabled ? (scheduler.running ? 'success' : 'info') : 'warning',
    icon: 'Timer',
  })
  items.push({
    label: '邮件通道',
    value: mail.enabled ? '已启用' : '未启用',
    extra: `${mail.endpoint || '—'}${mail.web_ui ? ` · ${mail.web_ui}` : ''}`,
    tagText: mail.enabled ? '正常' : '已暂停',
    tagType: mail.enabled ? 'success' : 'info',
    icon: 'Message',
  })
  items.push({
    label: '日志文件',
    value: `${logInfo.files ?? 0} 个文件`,
    extra: `${fmtBytes(logInfo.total_bytes)} / 上限 ${fmtBytes(logInfo.max_bytes)} · 备份 ${logInfo.backup_count ?? 0} 个`,
    tagText: '正常',
    tagType: 'success',
    icon: 'Document',
  })
  items.push({
    label: '指标采集',
    value: `${data.metrics?.window_minutes ?? '—'} 分钟窗口`,
    extra: `窗口内累计 ${fmtInt(data.metrics?.total)} 条请求`,
    tagText: '正常',
    tagType: 'success',
    icon: 'DataLine',
  })
  items.push({
    label: '运行时长',
    value: humanizeUptime(data.uptime_seconds),
    extra: `状态检查于 ${fmtDateTime(data.checked_at)}`,
    tagText: '正常',
    tagType: 'success',
    icon: 'Monitor',
  })
  return items
})

const trendOption = computed<any>(() => {
  const points = timeseries.value
  const xData = points.map((point) => String(point.minute || '').slice(11, 16) || String(point.minute || ''))
  const interval = points.length > 30 ? Math.ceil(points.length / 10) : 0
  return {
    color: ['#1f5fd6', '#d9822b', '#d64545'],
    grid: { left: 52, right: 60, top: 46, bottom: 30 },
    legend: {
      data: ['QPS', '平均耗时', '错误率'],
      top: 2,
      left: 76,
      itemGap: 18,
      itemWidth: 14,
      itemHeight: 8,
      textStyle: { color: '#5b6b7f', fontSize: 12 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(18, 35, 63, 0.92)',
      borderWidth: 0,
      textStyle: { color: '#e8f0ff', fontSize: 12 },
      formatter: (params: any) => {
        const rows = Array.isArray(params) ? params : [params]
        if (!rows.length) return ''
        const title = rows[0]?.axisValueLabel ?? rows[0]?.axisValue ?? ''
        const lines = rows.map((row: any) => {
          const unit = row.seriesName === '平均耗时' ? ' ms' : row.seriesName === '错误率' ? '%' : ' /s'
          return `${row.marker || ''}${row.seriesName}：<b>${fmtNum(row.value, 2)}</b>${unit}`
        })
        return `<div style="margin-bottom:4px;font-weight:600">${title}</div>${lines.join('<br/>')}`
      },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: xData,
      axisLine: { lineStyle: { color: '#dfe6f2' } },
      axisLabel: { color: '#7b8ba1', fontSize: 11, interval },
    },
    yAxis: [
      {
        type: 'value',
        name: '平均耗时 (ms)',
        nameTextStyle: { color: '#8b9aae', fontSize: 11, padding: [0, 0, 0, 8] },
        axisLabel: { color: '#7b8ba1', fontSize: 11 },
        splitLine: { lineStyle: { color: '#eef2f8' } },
      },
      {
        type: 'value',
        name: 'QPS / 错误率 (%)',
        nameTextStyle: { color: '#8b9aae', fontSize: 11, padding: [0, 8, 0, 0] },
        axisLabel: { color: '#7b8ba1', fontSize: 11 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'QPS',
        type: 'line',
        smooth: true,
        showSymbol: false,
        yAxisIndex: 1,
        data: points.map((point) => point.qps),
        lineStyle: { width: 2 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(31, 95, 214, 0.22)' },
              { offset: 1, color: 'rgba(31, 95, 214, 0.01)' },
            ],
          },
        },
      },
      {
        name: '平均耗时',
        type: 'line',
        smooth: true,
        showSymbol: false,
        yAxisIndex: 0,
        data: points.map((point) => point.avg_ms),
        lineStyle: { width: 2 },
      },
      {
        name: '错误率',
        type: 'line',
        smooth: true,
        showSymbol: false,
        yAxisIndex: 1,
        data: points.map((point) => point.error_rate),
        lineStyle: { width: 1.6, type: 'dashed' },
      },
    ],
  }
})

let refreshTimer: number | undefined
let lastWarnAt = 0

function warn(silent: boolean) {
  if (silent) return
  const now = Date.now()
  if (now - lastWarnAt < 2000) return
  lastWarnAt = now
  ElMessage.warning('数据服务暂不可用')
}

function fmtBytes(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function textOf(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  const obj = value as Record<string, unknown>
  if (typeof obj.name === 'string' && obj.name) return obj.name
  if (typeof obj.backend === 'string') return obj.backend
  if (typeof obj.ok === 'boolean') return obj.ok ? '连接正常' : '连接异常'
  try {
    return JSON.stringify(value).slice(0, 120)
  } catch {
    return '—'
  }
}

function healthText(value: unknown): string {
  const text = textOf(value)
  if (/不可用|失败|错误|断开|异常|error/i.test(text)) return '异常'
  return '正常'
}

function healthType(value: unknown): 'success' | 'warning' | 'danger' | 'info' {
  const text = textOf(value)
  if (/不可用|失败|错误|断开|异常|error/i.test(text)) return 'danger'
  if (/降级|degraded/i.test(text)) return 'warning'
  return 'success'
}

function humanizeUptime(seconds?: number): string {
  if (seconds === undefined || seconds === null || !Number.isFinite(seconds)) return '—'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days} 天 ${hours} 小时`
  if (hours > 0) return `${hours} 小时 ${mins} 分`
  return `${mins} 分`
}

function levelType(level?: string): 'danger' | 'warning' | 'success' | 'info' {
  const value = (level || '').toUpperCase()
  if (value === 'ERROR' || value === 'CRITICAL' || value === 'FATAL') return 'danger'
  if (value === 'WARN' || value === 'WARNING') return 'warning'
  if (value === 'INFO') return 'success'
  return 'info'
}

function statusType(code?: number): 'danger' | 'warning' | 'success' | 'info' {
  if (code === undefined || code === null) return 'info'
  if (code >= 500) return 'danger'
  if (code >= 400) return 'warning'
  if (code >= 200 && code < 400) return 'success'
  return 'info'
}

function pretty(row: unknown): string {
  try {
    return JSON.stringify(row, null, 2)
  } catch {
    return String(row)
  }
}

async function loadSummary(silent = false) {
  try {
    summary.value = await fetchMetricsSummary(minutes.value)
  } catch {
    if (!silent) summary.value = null
    warn(silent)
  }
}

async function loadTimeseries(silent = false) {
  chartLoading.value = true
  try {
    const points = await fetchMetricsTimeseries(minutes.value)
    timeseries.value = points || []
  } catch {
    if (!silent) timeseries.value = []
    warn(silent)
  } finally {
    chartLoading.value = false
  }
}

async function loadLogs(silent = false) {
  logLoading.value = true
  try {
    const result = await fetchLogs({
      limit: logLimit.value,
      level: logLevel.value || undefined,
      keyword: logKeyword.value.trim() || undefined,
    })
    logs.value = result?.list || []
    logStats.value = result?.stats || null
    logFailed.value = false
  } catch {
    logs.value = []
    logStats.value = null
    logFailed.value = true
    warn(silent)
  } finally {
    logLoading.value = false
  }
}

async function loadStatus(silent = false) {
  try {
    status.value = await fetchSystemStatus()
  } catch {
    if (!silent) status.value = null
    warn(silent)
  }
}

async function refreshAll(silent = false) {
  refreshing.value = !silent
  await Promise.allSettled([
    loadSummary(silent),
    loadTimeseries(silent),
    loadLogs(silent),
    loadStatus(silent),
  ])
  refreshing.value = false
}

function onMinutesChange() {
  loadSummary()
  loadTimeseries()
}

function resetLogs() {
  logLevel.value = ''
  logKeyword.value = ''
  logLimit.value = 100
  loadLogs()
}

async function onSendTestMail() {
  mailLoading.value = true
  try {
    const result = await sendTestMail()
    if (result?.sent) {
      ElMessage.success(`测试邮件已发送至 ${result.to || '默认收件人'}（${result.status || '已发送'}）`)
    } else {
      ElMessage.warning(`邮件发送失败：${result?.note || result?.status || 'SMTP 不可达'}`)
    }
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    mailLoading.value = false
  }
}

async function onTickTasks() {
  tickLoading.value = true
  try {
    const result = await tickTasks()
    const detail = `检查 ${result?.checked ?? 0} 个 · 到期 ${result?.due ?? 0} 个 · 触发 ${result?.triggered ?? 0} 个`
    if ((result?.failed ?? 0) > 0) {
      ElMessage.warning(`${detail} · 失败 ${result.failed} 个`)
    } else {
      ElMessage.success(detail)
    }
    await Promise.allSettled([loadStatus(true), loadSummary(true), loadTimeseries(true), loadLogs(true)])
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    tickLoading.value = false
  }
}

onMounted(async () => {
  await refreshAll()
  refreshTimer = window.setInterval(() => refreshAll(true), 30000)
})

onUnmounted(() => {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
})
</script>

<style scoped>
.monitor-page {
  min-width: 0;
}

.metrics-grid {
  grid-template-columns: repeat(6, minmax(0, 1fr));
}

.title-extra {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  font-weight: 400;
}

.log-stats {
  font-size: 12px;
  font-weight: 400;
  max-width: 60%;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-detail {
  padding: 8px 14px 12px;
  background: #f7f9fd;
}

.log-detail pre {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #33465f;
  white-space: pre-wrap;
  word-break: break-all;
}

.status-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.status-item {
  border: 1px solid var(--ap-border);
  border-radius: 8px;
  padding: 12px 14px;
  background: #fbfcff;
  min-width: 0;
}

.status-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.status-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ap-text);
}

.status-label .el-icon {
  color: var(--ap-primary);
}

.status-value {
  margin-top: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #16233a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-extra {
  margin-top: 4px;
  font-size: 12px;
  color: #8b9aae;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1500px) {
  .metrics-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 1200px) {
  .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .log-stats {
    max-width: 100%;
  }
}

@media (max-width: 900px) {
  .metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .status-grid {
    grid-template-columns: 1fr;
  }
}
</style>
