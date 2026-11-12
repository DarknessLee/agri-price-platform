<template>
  <div class="page">
    <PageHeader title="情景推演" subtitle="设定产量、运费、政策、替代品与气象冲击，评估未来价格走势与风险区间">
      <template #actions>
        <el-button :icon="Refresh" @click="loadHistory()">刷新记录</el-button>
      </template>
    </PageHeader>

    <div class="sim-layout">
      <section class="page-card">
        <div class="card-title"><span>参数设置</span></div>
        <el-form label-width="104px" label-position="left" size="default">
          <el-form-item label="情景名称">
            <el-input v-model="form.name" maxlength="40" placeholder="如：高温减产情景" />
          </el-form-item>
          <el-form-item label="情景模板">
            <div class="template-list">
              <button
                v-for="tpl in templates"
                :key="tpl.key"
                type="button"
                class="template-card"
                :class="{ active: form.scenario_type === tpl.key }"
                @click="applyTemplate(tpl)"
              >
                <strong>{{ tpl.name }}</strong>
                <span>{{ tpl.description }}</span>
              </button>
              <el-empty v-if="!templates.length" description="暂无情景模板" :image-size="48" />
            </div>
          </el-form-item>
          <div class="form-grid">
            <el-form-item label="品种">
              <el-select v-model="form.variety_id" placeholder="选择品种" filterable>
                <el-option v-for="item in varieties" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="地区">
              <el-select v-model="form.region_id" placeholder="选择地区" filterable>
                <el-option v-for="item in regions" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item :label="`预测期（${form.horizon} 天）`">
            <el-slider v-model="form.horizon" :min="7" :max="30" :step="1" />
          </el-form-item>
          <el-form-item :label="`产量冲击（${signed(form.yield_pct)}%）`">
            <el-slider v-model="form.yield_pct" :min="-30" :max="30" :step="1" />
          </el-form-item>
          <el-form-item :label="`运费冲击（${signed(form.freight_pct)}%）`">
            <el-slider v-model="form.freight_pct" :min="-30" :max="30" :step="1" />
          </el-form-item>
          <el-form-item :label="`政策冲击（${signed(form.policy_pct)}%）`">
            <el-slider v-model="form.policy_pct" :min="-30" :max="30" :step="1" />
          </el-form-item>
          <el-form-item :label="`替代品冲击（${signed(form.substitute_pct)}%）`">
            <el-slider v-model="form.substitute_pct" :min="-30" :max="30" :step="1" />
          </el-form-item>
          <el-form-item :label="`气象等级（${weatherText}）`">
            <el-slider v-model="form.weather_level" :min="0" :max="3" :step="1" :marks="weatherMarks" />
          </el-form-item>
          <div class="form-actions">
            <el-button type="primary" :loading="running" @click="runScenario">开始推演</el-button>
            <el-button @click="resetForm">重置</el-button>
          </div>
        </el-form>
      </section>

      <section class="page-card result-card">
        <div class="card-title">
          <span>推演结果</span>
          <el-tag v-if="result?.risk_level" :type="levelTagType(result.risk_level)" effect="light">
            风险等级：{{ result.risk_level }}
          </el-tag>
        </div>
        <el-empty v-if="!result" description="设置参数后点击“开始推演”，查看价格走势与置信区间" />
        <template v-else>
          <div class="result-summary">
            <div class="change-box">
              <span class="muted">预测期价格变动</span>
              <strong :class="(result.price_change_pct ?? 0) >= 0 ? 'text-up' : 'text-down'">
                {{ fmtPct(result.price_change_pct, 2) }}
              </strong>
              <span class="muted">{{ trendArrow(result.price_change_pct) }} {{ result.trend || '—' }}</span>
            </div>
            <div class="range-box">
              <div v-for="item in rangeItems" :key="item.label" class="range-item">
                <span>{{ item.label }}</span>
                <strong>{{ fmtNum(item.value) }}</strong>
              </div>
            </div>
          </div>

          <BaseChart :option="chartOption" :height="320" :empty="!hasChart" empty-text="暂无走势数据" />

          <div class="factor-advice">
            <div>
              <h4>主要影响因素</h4>
              <ul class="factor-list">
                <li v-for="(factor, idx) in result.factors || []" :key="idx">
                  <span class="factor-name">{{ factor.name }}</span>
                  <span class="mono" :class="(factor.impact_pct ?? 0) >= 0 ? 'text-up' : 'text-down'">
                    {{ fmtPct(factor.impact_pct, 2) }}
                  </span>
                  <span class="muted factor-desc">{{ factor.description }}</span>
                </li>
                <li v-if="!(result.factors && result.factors.length)" class="muted">暂无因素拆解</li>
              </ul>
            </div>
            <div>
              <h4>决策建议</h4>
              <ul class="advice-list">
                <li v-for="(item, idx) in result.advice || []" :key="idx">{{ item }}</li>
                <li v-if="!(result.advice && result.advice.length)" class="muted">暂无建议</li>
              </ul>
            </div>
          </div>
        </template>
      </section>
    </div>

    <section class="page-card">
      <div class="card-title">
        <span>情景历史</span>
        <span class="muted">共 {{ fmtInt(history.total) }} 条</span>
      </div>
      <el-table v-loading="historyLoading" :data="history.list" empty-text="暂无情景记录">
        <el-table-column prop="name" label="情景名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="类型" width="100">
          <template #default="scope">{{ typeName(scope.row.scenario_type) }}</template>
        </el-table-column>
        <el-table-column prop="variety" label="品种" width="90" />
        <el-table-column prop="region" label="地区" width="110" />
        <el-table-column label="预测期" width="90">
          <template #default="scope">{{ scope.row.horizon ? `${scope.row.horizon} 天` : '—' }}</template>
        </el-table-column>
        <el-table-column label="价格变动" width="110" align="right">
          <template #default="scope">
            <span :class="(scope.row.price_change_pct ?? 0) >= 0 ? 'text-up' : 'text-down'">
              {{ fmtPct(scope.row.price_change_pct, 2) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="风险等级" width="96" align="center">
          <template #default="scope">
            <el-tag v-if="scope.row.risk_level" :type="levelTagType(scope.row.risk_level)" size="small" effect="light">
              {{ scope.row.risk_level }}
            </el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_by" label="创建人" width="100" />
        <el-table-column label="创建时间" width="160">
          <template #default="scope">{{ fmtDateTime(scope.row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="scope">
            <el-button link type="danger" :disabled="!canRun" @click="removeScenario(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="historyPage"
          layout="total, prev, pager, next"
          :total="history.total"
          :page-size="historyPageSize"
          @current-change="loadHistory"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { EChartsOption } from 'echarts'
import { Refresh } from '@element-plus/icons-vue'
import api, { type Paged } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import BaseChart from '@/components/BaseChart.vue'
import { useAuthStore } from '@/stores/auth'
import { fmtDateTime, fmtInt, fmtNum, fmtPct, levelTagType, trendArrow } from '@/utils/format'
import type { DictOption, MetaDicts } from '@/types'

interface ScenarioTemplate {
  key: string
  name: string
  description: string
  defaults: Record<string, unknown>
}

interface ScenarioHistoryRow {
  id: number
  name: string
  scenario_type: string
  variety?: string
  region?: string
  horizon?: number
  price_change_pct?: number
  risk_level?: string
  created_by?: string
  created_at?: string
}

interface ScenarioChart {
  dates: string[]
  base: number[]
  predicted: number[]
  lower: number[]
  upper: number[]
}

interface ScenarioFactor {
  name: string
  impact_pct: number
  description: string
}

interface ScenarioResult {
  id: number
  name: string
  scenario_type: string
  price_change_pct?: number
  price_range?: { low: number; mid: number; high: number }
  risk_level?: string
  trend?: string
  chart?: ScenarioChart
  factors?: ScenarioFactor[]
  advice?: string[]
  created_at?: string
}

const auth = useAuthStore()
const canRun = computed(() => auth.hasPerm('scenario:run'))

const templates = ref<ScenarioTemplate[]>([])
const varieties = ref<DictOption[]>([])
const regions = ref<DictOption[]>([])
const result = ref<ScenarioResult | null>(null)
const running = ref(false)

const form = reactive({
  name: '自定义情景',
  scenario_type: 'weather',
  variety_id: undefined as number | undefined,
  region_id: undefined as number | undefined,
  horizon: 14,
  yield_pct: 0,
  freight_pct: 0,
  policy_pct: 0,
  substitute_pct: 0,
  weather_level: 0,
})

const weatherMarks: Record<number, string> = { 0: '正常', 1: '轻度', 2: '中度', 3: '重度' }
const weatherText = computed(() => weatherMarks[form.weather_level] || '正常')

const history = reactive<{ list: ScenarioHistoryRow[]; total: number }>({ list: [], total: 0 })
const historyLoading = ref(false)
const historyPage = ref(1)
const historyPageSize = 10

function signed(value: number): string {
  return value > 0 ? `+${value}` : String(value)
}

function typeName(key: string): string {
  const matched = templates.value.find((item) => item.key === key)
  return matched ? matched.name : key || '—'
}

const rangeItems = computed(() => {
  const range = result.value?.price_range
  if (!range) return []
  return [
    { label: '价格低位', value: range.low },
    { label: '价格中位', value: range.mid },
    { label: '价格高位', value: range.high },
  ]
})

const hasChart = computed(() => Boolean(result.value?.chart?.dates?.length))

const chartOption = computed<EChartsOption>(() => {
  const chart = result.value?.chart
  if (!chart || !chart.dates?.length) return {}
  const band = chart.upper.map((upper, idx) => Number((upper - (chart.lower[idx] ?? upper)).toFixed(2)))
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (raw: unknown) => {
        const list = raw as Array<{ dataIndex: number }>
        if (!list.length) return ''
        const idx = list[0].dataIndex
        const rows: Array<[string, number | string]> = [
          ['基线价格', chart.base[idx]],
          ['预测价格', chart.predicted[idx]],
          ['置信区间', `${fmtNum(chart.lower[idx])} ~ ${fmtNum(chart.upper[idx])}`],
        ]
        return `${chart.dates[idx]}<br/>${rows
          .map(([label, value]) => `${label}：${typeof value === 'number' ? fmtNum(value) : value}`)
          .join('<br/>')}`
      },
    },
    legend: { data: ['基线价格', '预测价格'], top: 0, right: 0, itemWidth: 14 },
    grid: { left: 10, right: 18, top: 40, bottom: 6, containLabel: true },
    xAxis: {
      type: 'category',
      data: chart.dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#dfe6f0' } },
      axisLabel: { color: '#7b8ba1' },
    },
    yAxis: {
      type: 'value',
      name: '价格',
      splitLine: { lineStyle: { color: '#eef2f8' } },
      axisLabel: { color: '#7b8ba1' },
    },
    series: [
      {
        name: '区间下界',
        type: 'line',
        stack: 'ci',
        data: chart.lower,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: 'transparent' },
        tooltip: { show: false },
      },
      {
        name: '区间上界',
        type: 'line',
        stack: 'ci',
        data: band,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: 'rgba(31, 95, 214, 0.10)' },
        tooltip: { show: false },
      },
      {
        name: '基线价格',
        type: 'line',
        data: chart.base,
        symbol: 'none',
        smooth: true,
        lineStyle: { type: 'dashed', color: '#8b9aae', width: 1.5 },
        itemStyle: { color: '#8b9aae' },
      },
      {
        name: '预测价格',
        type: 'line',
        data: chart.predicted,
        symbol: 'none',
        smooth: true,
        lineStyle: { color: '#1f5fd6', width: 2.5 },
        itemStyle: { color: '#1f5fd6' },
        areaStyle: { color: 'rgba(31, 95, 214, 0.05)' },
      },
    ],
  }
})

function applyTemplate(tpl: ScenarioTemplate) {
  form.scenario_type = tpl.key
  form.name = tpl.name
  const defaults = (tpl.defaults || {}) as Record<string, unknown>
  const nested = defaults.shock as Record<string, unknown> | undefined
  const source: Record<string, unknown> = nested && typeof nested === 'object' ? { ...defaults, ...nested } : defaults
  if (typeof source.yield_pct === 'number') form.yield_pct = source.yield_pct
  if (typeof source.freight_pct === 'number') form.freight_pct = source.freight_pct
  if (typeof source.policy_pct === 'number') form.policy_pct = source.policy_pct
  if (typeof source.substitute_pct === 'number') form.substitute_pct = source.substitute_pct
  if (typeof source.weather_level === 'number') form.weather_level = source.weather_level
}

function resetForm() {
  form.name = '自定义情景'
  form.scenario_type = 'weather'
  form.horizon = 14
  form.yield_pct = 0
  form.freight_pct = 0
  form.policy_pct = 0
  form.substitute_pct = 0
  form.weather_level = 0
  result.value = null
}

async function loadMeta() {
  try {
    const dicts = await api.get<MetaDicts>('/meta/dicts')
    varieties.value = dicts.varieties || []
    regions.value = dicts.regions || []
    if (form.variety_id === undefined && varieties.value.length) form.variety_id = varieties.value[0].id
    if (form.region_id === undefined && regions.value.length) form.region_id = regions.value[0].id
  } catch {
    ElMessage.warning('数据服务暂不可用')
  }
}

async function loadTemplates() {
  try {
    templates.value = (await api.get<ScenarioTemplate[]>('/scenarios/templates')) || []
  } catch {
    ElMessage.warning('数据服务暂不可用')
  }
}

async function loadHistory(page = historyPage.value) {
  historyPage.value = page
  historyLoading.value = true
  try {
    const data = await api.get<Paged<ScenarioHistoryRow>>('/scenarios', {
      page,
      page_size: historyPageSize,
    })
    history.list = data.list || []
    history.total = data.total || 0
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    historyLoading.value = false
  }
}

async function runScenario() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入情景名称')
    return
  }
  if (!form.variety_id || !form.region_id) {
    ElMessage.warning('请选择品种与地区')
    return
  }
  const shock: Record<string, number> = {
    yield_pct: form.yield_pct,
    freight_pct: form.freight_pct,
    policy_pct: form.policy_pct,
    substitute_pct: form.substitute_pct,
  }
  if (form.weather_level > 0) shock.weather_level = form.weather_level
  running.value = true
  try {
    result.value = await api.post<ScenarioResult>('/scenarios', {
      name: form.name.trim(),
      scenario_type: form.scenario_type,
      variety_id: form.variety_id,
      region_id: form.region_id,
      horizon: form.horizon,
      shock,
    })
    ElMessage.success('情景推演完成')
    await loadHistory(1)
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    running.value = false
  }
}

async function removeScenario(row: ScenarioHistoryRow) {
  try {
    await ElMessageBox.confirm(`确认删除情景「${row.name}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await api.delete(`/scenarios/${row.id}`)
    ElMessage.success('已删除')
    await loadHistory(history.list.length === 1 && historyPage.value > 1 ? historyPage.value - 1 : historyPage.value)
  } catch {
    ElMessage.warning('数据服务暂不可用')
  }
}

onMounted(() => {
  loadMeta()
  loadTemplates()
  loadHistory(1)
})
</script>

<style scoped>
.sim-layout {
  display: grid;
  grid-template-columns: 430px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.result-card {
  min-height: 520px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 8px;
}

.template-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}

.template-card {
  padding: 8px 10px;
  text-align: left;
  background: #f7f9fd;
  border: 1px solid #e4e9f2;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.template-card:hover {
  border-color: #b9cdf5;
}

.template-card.active {
  border-color: var(--ap-primary);
  background: #eef4ff;
}

.template-card strong {
  display: block;
  font-size: 13px;
  color: #1c2a3a;
}

.template-card span {
  display: block;
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.4;
  color: #7b8ba1;
}

.template-list :deep(.el-empty) {
  grid-column: 1 / -1;
  padding: 6px 0;
}

.form-actions {
  display: flex;
  gap: 10px;
  padding-left: 104px;
}

.result-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 6px;
}

.change-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 180px;
  padding: 10px 14px;
  background: #f7f9fd;
  border-radius: 8px;
}

.change-box strong {
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}

.range-box {
  display: flex;
  flex: 1;
  gap: 10px;
  min-width: 260px;
}

.range-item {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  min-width: 88px;
  padding: 10px 12px;
  background: #f7f9fd;
  border-radius: 8px;
}

.range-item span {
  font-size: 12px;
  color: #7b8ba1;
}

.range-item strong {
  font-size: 18px;
  color: #16233a;
  font-variant-numeric: tabular-nums;
}

.factor-advice {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
  gap: 18px;
  margin-top: 14px;
}

.factor-advice h4 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: #40536b;
}

.factor-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.factor-list li {
  display: grid;
  grid-template-columns: 120px 72px minmax(0, 1fr);
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
}

.factor-name {
  color: #40536b;
  font-weight: 500;
}

.factor-desc {
  font-size: 12px;
  line-height: 1.5;
}

.advice-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.8;
  color: #40536b;
}

.advice-list li.muted {
  list-style: none;
  margin-left: -18px;
}

@media (max-width: 1280px) {
  .sim-layout {
    grid-template-columns: 1fr;
  }

  .result-card {
    min-height: 0;
  }
}

@media (max-width: 900px) {
  .factor-advice {
    grid-template-columns: 1fr;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
