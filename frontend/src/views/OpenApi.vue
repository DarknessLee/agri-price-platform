<template>
  <div class="page">
    <PageHeader title="开放 API" subtitle="面向第三方系统的数据开放接口，统一鉴权方式与响应结构">
      <template #actions>
        <el-button :icon="Refresh" :loading="metricsLoading" @click="loadMetrics">刷新指标</el-button>
        <el-button type="primary" plain :icon="CopyDocument" @click="copyText(apiBase, '接入地址已复制')">
          复制接入地址
        </el-button>
      </template>
    </PageHeader>

    <div v-loading="metricsLoading" class="kpi-grid">
      <KpiCard
        label="接入品种"
        :value="metrics.variety_count ?? '—'"
        unit="个"
        icon="Goods"
        tone="blue"
        :hint="metricsHints.source"
      />
      <KpiCard
        label="覆盖地区"
        :value="metrics.region_count ?? '—'"
        unit="个"
        icon="Location"
        tone="green"
        :hint="metricsHints.latest"
      />
      <KpiCard
        label="价格记录"
        :value="fmtInt(metrics.record_count)"
        unit="条"
        icon="DataLine"
        tone="orange"
        :hint="metricsHints.normal"
      />
      <KpiCard
        label="数据完整率"
        :value="fmtPct(metrics.completeness, 1, false)"
        icon="CircleCheck"
        tone="purple"
        :hint="metricsHints.alerts"
      />
    </div>

    <div class="page-card">
      <div class="card-title"><span>接入说明</span></div>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="接入地址">
          <span class="mono">{{ apiBase }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="请求方法">GET，参数通过 Query String 传递</el-descriptions-item>
        <el-descriptions-item label="鉴权方式">
          <span class="mono">Authorization: Bearer &lt;token&gt;</span>
        </el-descriptions-item>
        <el-descriptions-item label="获取 Token">
          <span class="mono">POST /api/auth/login</span>
        </el-descriptions-item>
        <el-descriptions-item label="统一响应">
          <span class="mono">{ "code": "0", "message": "success", "data": ... }</span>
        </el-descriptions-item>
        <el-descriptions-item label="分页结构">
          <span class="mono">data.list / data.total / data.page / data.page_size</span>
        </el-descriptions-item>
      </el-descriptions>
      <el-alert type="info" :closable="false" show-icon style="margin-top: 14px">
        <template #title>错误码说明</template>
        <div class="error-codes">
          <span><b class="mono">E4001</b> 参数校验失败</span>
          <span><b class="mono">E4002</b> 业务规则不允许</span>
          <span><b class="mono">E4010</b> 未登录或 Token 失效</span>
          <span><b class="mono">E4030</b> 权限不足</span>
          <span><b class="mono">E4040</b> 资源不存在</span>
          <span><b class="mono">E4090</b> 资源冲突</span>
          <span><b class="mono">E5000</b> 服务内部错误</span>
        </div>
        <div class="muted" style="margin-top: 6px">
          调试请求会自动携带当前登录账号的 Token；第三方系统需先调用登录接口获取 token，再以 Bearer 方式访问。
        </div>
      </el-alert>
    </div>

    <div class="api-list">
      <div v-for="item in endpoints" :key="item.path" class="page-card api-card">
        <div class="api-head">
          <div class="flex gap-8 api-title-line">
            <el-tag type="success" effect="dark" class="method-tag mono">GET</el-tag>
            <span class="api-path mono">/open/v1/{{ item.path }}</span>
            <span class="api-title">{{ item.title }}</span>
          </div>
          <div class="flex gap-8">
            <el-button link type="primary" :icon="CopyDocument" @click="copyText(curlOf(item), 'cURL 命令已复制')">
              复制 cURL
            </el-button>
            <el-button link type="primary" :icon="VideoPlay" @click="toggleDebug(item.path)">
              {{ openDebug === item.path ? '收起调试' : '调试' }}
            </el-button>
          </div>
        </div>

        <p class="api-desc">{{ item.description }}</p>

        <el-table :data="item.params" size="small" border class="param-table">
          <el-table-column prop="name" label="参数" width="150">
            <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column label="必填" width="70" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.required" type="danger" effect="plain" size="small">必填</el-tag>
              <span v-else class="muted">否</span>
            </template>
          </el-table-column>
          <el-table-column prop="type" label="类型" width="90" align="center" />
          <el-table-column prop="description" label="说明" min-width="240" show-overflow-tooltip />
          <el-table-column prop="default" label="示例值" width="150">
            <template #default="{ row }"><span class="mono">{{ row.default || '—' }}</span></template>
          </el-table-column>
          <template #empty>
            <el-empty description="该接口无需查询参数" :image-size="60" />
          </template>
        </el-table>

        <el-collapse-transition>
          <div v-show="openDebug === item.path" class="debug-panel">
            <div class="debug-head">
              <span class="debug-title"><el-icon><Connection /></el-icon> 在线调试</span>
              <span class="muted">请求地址：<span class="mono">{{ apiBase }}/{{ item.path }}</span></span>
            </div>
            <div v-if="item.params.length" class="debug-grid">
              <div v-for="param in item.params" :key="param.name" class="debug-field">
                <label class="debug-label">
                  <span class="mono">{{ param.name }}</span>
                  <el-tag v-if="param.required" type="danger" effect="plain" size="small">必填</el-tag>
                </label>
                <el-input
                  v-model="debugValues[item.path][param.name]"
                  size="small"
                  :placeholder="param.default || `请输入 ${param.name}`"
                  clearable
                />
              </div>
            </div>
            <div v-else class="muted" style="margin-bottom: 10px">该接口无需查询参数，直接发起请求即可。</div>
            <div class="debug-actions">
              <el-button type="primary" size="small" :loading="debugLoading === item.path" @click="runEndpoint(item)">
                发起请求
              </el-button>
              <el-button size="small" :disabled="!debugResults[item.path]" @click="clearResult(item.path)">清空结果</el-button>
            </div>
            <div v-if="debugResults[item.path]" class="debug-result-wrap">
              <div class="debug-result-head">
                <span class="muted">响应结果</span>
                <el-button link type="primary" :icon="CopyDocument" @click="copyText(debugResults[item.path].text, '响应结果已复制')">
                  复制 JSON
                </el-button>
              </div>
              <pre class="debug-result mono" v-html="debugResults[item.path].html"></pre>
            </div>
          </div>
        </el-collapse-transition>

        <div class="curl-block">
          <div class="muted curl-label">cURL 示例</div>
          <pre class="curl mono">{{ curlOf(item) }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, CopyDocument, Refresh, VideoPlay } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import KpiCard from '@/components/KpiCard.vue'
import api, { ApiError } from '@/api/client'
import { fmtDate, fmtInt, fmtPct } from '@/utils/format'

interface ApiParam {
  name: string
  required: boolean
  type: string
  description: string
  default: string
}

interface ApiEndpoint {
  path: string
  title: string
  description: string
  params: ApiParam[]
}

interface MetricsData {
  variety_count?: number
  region_count?: number
  source_count?: number
  record_count?: number
  normal_record_count?: number
  completeness?: number
  latest_price_date?: string
  open_alert_count?: number
  generated_at?: string
}

const apiBase = 'http://127.0.0.1:8017/api/open/v1'

const endpoints: ApiEndpoint[] = [
  {
    path: 'prices',
    title: '价格数据查询',
    description: '按品种、地区与日期范围查询价格记录，返回日期、品种、地区、市场类型、价格与计量单位。',
    params: [
      { name: 'variety_code', required: false, type: 'string', description: '品种编码，如 pig（生猪）', default: 'pig' },
      { name: 'region_code', required: false, type: 'string', description: '地区编码，如 110000（北京）', default: '110000' },
      { name: 'start', required: false, type: 'string', description: '开始日期，格式 YYYY-MM-DD', default: '2026-10-01' },
      { name: 'end', required: false, type: 'string', description: '结束日期，格式 YYYY-MM-DD', default: '2026-10-31' },
      { name: 'limit', required: false, type: 'number', description: '返回条数上限，默认 100', default: '100' },
    ],
  },
  {
    path: 'forecast',
    title: '价格预测查询',
    description: '按品种与地区返回未来若干天的价格预测点值、置信区间、趋势方向与模型 MAPE。',
    params: [
      { name: 'variety_code', required: true, type: 'string', description: '品种编码，如 pig（生猪）', default: 'pig' },
      { name: 'region_code', required: true, type: 'string', description: '地区编码，如 110000（北京）', default: '110000' },
      { name: 'horizon', required: false, type: 'number', description: '预测天数，默认 7', default: '7' },
    ],
  },
  {
    path: 'alerts',
    title: '预警事件查询',
    description: '查询价格预警事件，支持按预警等级与处理状态筛选，返回预警标题、日期与当前状态。',
    params: [
      { name: 'level', required: false, type: 'string', description: '预警等级：高 / 中 / 低', default: '高' },
      { name: 'status', required: false, type: 'string', description: '处理状态：待处理 / 处理中 / 已关闭', default: '待处理' },
      { name: 'limit', required: false, type: 'number', description: '返回条数上限，默认 20', default: '20' },
    ],
  },
  {
    path: 'reports',
    title: '报告列表查询',
    description: '查询已生成的价格监测报告，按报告类型筛选，返回标题、类型、统计周期与生成时间。',
    params: [
      { name: 'report_type', required: false, type: 'string', description: '报告类型：daily / weekly / monthly', default: 'daily' },
      { name: 'limit', required: false, type: 'number', description: '返回条数上限，默认 10', default: '10' },
    ],
  },
  {
    path: 'metrics',
    title: '数据概览',
    description: '获取平台数据开放概览指标：品种数、地区数、数据源数、记录数、完整率与最新价格日期。',
    params: [],
  },
]

const metrics = ref<MetricsData>({})
const metricsLoading = ref(false)

const openDebug = ref('')
const debugLoading = ref('')
const debugValues = reactive<Record<string, Record<string, string>>>({})
const debugResults = reactive<Record<string, { html: string; text: string }>>({})

for (const item of endpoints) {
  const values: Record<string, string> = {}
  for (const param of item.params) values[param.name] = param.default
  debugValues[item.path] = values
}

const metricsHints = computed(() => ({
  source: metrics.value.source_count != null ? `数据源 ${metrics.value.source_count} 个` : '数据源数量未知',
  latest: metrics.value.latest_price_date ? `最新价格日期 ${fmtDate(metrics.value.latest_price_date)}` : '暂无最新价格日期',
  normal: metrics.value.normal_record_count != null ? `有效记录 ${fmtInt(metrics.value.normal_record_count)} 条` : '暂无记录统计',
  alerts: metrics.value.open_alert_count != null ? `未处理预警 ${fmtInt(metrics.value.open_alert_count)} 条` : '暂无预警统计',
}))

function errorOf(err: unknown): string {
  if (err instanceof ApiError) return err.message
  const payload = (err as { response?: { data?: { message?: string } } })?.response?.data
  return payload?.message || ''
}

function warn(err: unknown) {
  const message = errorOf(err)
  ElMessage.warning(message && message !== 'Network Error' ? message : '数据服务暂不可用')
}

async function loadMetrics() {
  metricsLoading.value = true
  try {
    metrics.value = await api.get<MetricsData>('/open/v1/metrics')
  } catch (err) {
    metrics.value = {}
    warn(err)
  } finally {
    metricsLoading.value = false
  }
}

function toggleDebug(path: string) {
  openDebug.value = openDebug.value === path ? '' : path
}

function queryParams(item: ApiEndpoint): Record<string, string> {
  const values = debugValues[item.path] || {}
  const params: Record<string, string> = {}
  for (const param of item.params) {
    const value = (values[param.name] || '').trim()
    if (value) params[param.name] = value
  }
  return params
}

function curlOf(item: ApiEndpoint): string {
  const query = Object.entries(queryParams(item))
    .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
    .join('&')
  const url = `${apiBase}/${item.path}${query ? `?${query}` : ''}`
  return `curl -X GET "${url}" \\\n  -H "Authorization: Bearer <token>"`
}

async function runEndpoint(item: ApiEndpoint) {
  debugLoading.value = item.path
  try {
    const data = item.path === 'metrics'
      ? await api.get<unknown>('/open/v1/metrics')
      : await api.get<unknown>(`/open/v1/${item.path}`, queryParams(item))
    debugResults[item.path] = {
      html: highlightJson(data),
      text: JSON.stringify(data, null, 2) ?? 'null',
    }
  } catch (err) {
    delete debugResults[item.path]
    warn(err)
  } finally {
    debugLoading.value = ''
  }
}

function clearResult(path: string) {
  delete debugResults[path]
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function highlightJson(value: unknown): string {
  const text = escapeHtml(JSON.stringify(value, null, 2) ?? 'null')
  const pattern = /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"\s*:)|("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*")|(\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|(\btrue\b|\bfalse\b|\bnull\b)/g
  return text.replace(pattern, (match, key, str, num) => {
    if (key) return `<span class="j-key">${key}</span>`
    if (str) return `<span class="j-str">${str}</span>`
    if (num) return `<span class="j-num">${num}</span>`
    return `<span class="j-bool">${match}</span>`
  })
}

async function copyText(text: string, tip: string) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const area = document.createElement('textarea')
      area.value = text
      area.style.position = 'fixed'
      area.style.opacity = '0'
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      document.body.removeChild(area)
    }
    ElMessage.success(tip)
  } catch {
    ElMessage.warning('复制失败，请手动选择文本复制')
  }
}

onMounted(loadMetrics)
</script>

<style scoped>
.api-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.api-card {
  padding-bottom: 16px;
}

.api-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.api-title-line {
  flex-wrap: wrap;
}

.method-tag {
  letter-spacing: 0.5px;
}

.api-path {
  font-size: 14px;
  font-weight: 600;
  color: var(--ap-text);
}

.api-title {
  font-size: 13px;
  color: var(--ap-text-secondary);
}

.api-desc {
  margin: 8px 0 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--ap-text-secondary);
}

.param-table {
  margin-bottom: 12px;
}

.param-table :deep(.el-table__cell) {
  padding: 7px 0;
}

.debug-panel {
  margin: 12px 0 4px;
  padding: 14px 16px;
  background: #f7f9fd;
  border: 1px solid var(--ap-border);
  border-radius: var(--ap-radius);
}

.debug-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.debug-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #40536b;
}

.debug-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px 14px;
}

.debug-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.debug-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #5b6b7f;
}

.debug-actions {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.debug-result-wrap {
  margin-top: 12px;
}

.debug-result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 12px;
}

.debug-result {
  margin: 0;
  padding: 12px 14px;
  max-height: 340px;
  overflow: auto;
  background: #101f38;
  border-radius: 8px;
  color: #d7e2f4;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-all;
}

.debug-result :deep(.j-key) {
  color: #8ab4ff;
}

.debug-result :deep(.j-str) {
  color: #7fd6a4;
}

.debug-result :deep(.j-num) {
  color: #f0b866;
}

.debug-result :deep(.j-bool) {
  color: #d9a2ff;
}

.curl-block {
  margin-top: 12px;
}

.curl-label {
  font-size: 12px;
  margin-bottom: 6px;
}

.curl {
  margin: 0;
  padding: 10px 14px;
  background: #f4f6fb;
  border: 1px dashed var(--ap-border);
  border-radius: 8px;
  color: #40536b;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
}

.error-codes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 20px;
  font-size: 12px;
  margin-top: 4px;
}

.error-codes b {
  color: #17479f;
}
</style>
