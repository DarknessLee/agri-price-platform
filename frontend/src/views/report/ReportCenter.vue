<template>
  <div class="page">
    <PageHeader title="报告中心" subtitle="按日、周、月生成价格分析报告，支持在线预览与 HTML / Markdown 下载">
      <template #actions>
        <el-button :icon="Refresh" @click="loadReports()">刷新</el-button>
        <el-button v-if="canGenerate" type="primary" :icon="Plus" @click="openCreate">生成报告</el-button>
      </template>
    </PageHeader>

    <section class="page-card">
      <div class="toolbar">
        <el-select v-model="filterType" placeholder="报告类型" clearable style="width: 150px" @change="loadReports(1)">
          <el-option label="全部类型" value="" />
          <el-option v-for="item in reportTypes" :key="item.key" :label="item.name" :value="item.key" />
        </el-select>
        <span class="muted">共 {{ fmtInt(total) }} 份报告</span>
        <div class="grow" />
      </div>

      <el-table v-loading="loading" :data="rows" empty-text="暂无报告，点击右上角生成报告">
        <el-table-column prop="title" label="报告标题" min-width="240" show-overflow-tooltip />
        <el-table-column label="类型" width="86" align="center">
          <template #default="scope">
            <el-tag size="small" effect="light">{{ typeName(scope.row.report_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="统计周期" width="190">
          <template #default="scope">
            {{ fmtDate(scope.row.period_start) }} ~ {{ fmtDate(scope.row.period_end) }}
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90" align="center">
          <template #default="scope">
            <el-tag :type="statusTag(scope.row.status)" size="small" effect="light">{{ scope.row.status || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="summary" label="摘要" min-width="220" show-overflow-tooltip>
          <template #default="scope">{{ scope.row.summary || '—' }}</template>
        </el-table-column>
        <el-table-column prop="created_by" label="生成人" width="100" />
        <el-table-column label="生成时间" width="160">
          <template #default="scope">{{ fmtDateTime(scope.row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="openDetail(scope.row.id)">查看</el-button>
            <el-button link type="primary" @click="downloadReport(scope.row, 'html')">下载</el-button>
            <el-button v-if="canGenerate" link type="danger" @click="removeReport(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="page"
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          @current-change="loadReports"
        />
      </div>
    </section>

    <el-dialog v-model="createVisible" title="生成报告" width="580px" :close-on-click-modal="false">
      <el-form label-width="88px">
        <el-form-item label="报告类型">
          <el-radio-group v-model="createForm.report_type">
            <el-radio-button v-for="item in reportTypes" :key="item.key" :value="item.key">
              {{ item.name }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="统计周期">
          <el-date-picker
            v-model="createForm.range"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="品种">
          <el-select v-model="createForm.variety_ids" multiple collapse-tags collapse-tags-tooltip placeholder="全部品种" style="width: 100%">
            <el-option v-for="item in varieties" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="地区">
          <el-select v-model="createForm.region_ids" multiple collapse-tags collapse-tags-tooltip placeholder="全部地区" style="width: 100%">
            <el-option v-for="item in regions" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <div class="muted form-tip">留空表示覆盖全部品种与地区；报告生成后自动打开详情。</div>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="generateReport">生成报告</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="drawerVisible" :title="detail?.title || '报告详情'" size="62%" destroy-on-close>
      <div v-loading="detailLoading" class="report-detail">
        <div v-if="detail" class="report-meta">
          <el-tag size="small" effect="light">{{ typeName(detail.report_type) }}</el-tag>
          <el-tag :type="statusTag(detail.status)" size="small" effect="light">{{ detail.status || '—' }}</el-tag>
          <span>统计周期：{{ fmtDate(detail.period_start) }} ~ {{ fmtDate(detail.period_end) }}</span>
          <span>生成人：{{ detail.created_by || '—' }}</span>
          <span>生成时间：{{ fmtDateTime(detail.created_at) }}</span>
          <div class="grow" />
          <el-button size="small" :icon="Download" @click="downloadDetail('html')">下载 HTML</el-button>
          <el-button size="small" @click="downloadDetail('md')">下载 Markdown</el-button>
        </div>
        <div v-if="detail" class="report-content" v-html="detail.content_html || '<p>报告正文为空</p>'" />
        <el-empty v-else-if="!detailLoading" description="报告详情加载失败" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Plus, Refresh } from '@element-plus/icons-vue'
import api, { type Paged } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { useAuthStore } from '@/stores/auth'
import { fmtDate, fmtDateTime, fmtInt } from '@/utils/format'
import type { DictOption, MetaDicts } from '@/types'

interface ReportItem {
  id: number
  title: string
  report_type: string
  period_start: string
  period_end: string
  status: string
  summary?: string
  created_by?: string
  created_at: string
}

interface ReportDetail extends ReportItem {
  content_html?: string
  metrics?: Record<string, unknown>
}

interface GenerateResult {
  id: number
  title: string
  status: string
  content_html: string
}

const reportTypes: Array<{ key: string; name: string }> = [
  { key: 'daily', name: '日报' },
  { key: 'weekly', name: '周报' },
  { key: 'monthly', name: '月报' },
]

const auth = useAuthStore()
const canGenerate = computed(() => auth.hasPerm('report:generate'))

const rows = ref<ReportItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const loading = ref(false)
const filterType = ref('')

const varieties = ref<DictOption[]>([])
const regions = ref<DictOption[]>([])

const createVisible = ref(false)
const creating = ref(false)
const createForm = reactive({
  report_type: 'daily',
  range: [] as string[],
  variety_ids: [] as number[],
  region_ids: [] as number[],
})

const drawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<ReportDetail | null>(null)

function typeName(key?: string): string {
  const matched = reportTypes.find((item) => item.key === key)
  return matched ? matched.name : key || '—'
}

function statusTag(status?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (!status) return 'info'
  if (['已生成', '已完成', '成功'].includes(status)) return 'success'
  if (['生成中', '处理中', '待生成'].includes(status)) return 'warning'
  if (['失败', '异常'].includes(status)) return 'danger'
  return 'info'
}

function toDateStr(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function defaultRange(): string[] {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - 6)
  return [toDateStr(start), toDateStr(end)]
}

async function loadMeta() {
  try {
    const dicts = await api.get<MetaDicts>('/meta/dicts')
    varieties.value = dicts.varieties || []
    regions.value = dicts.regions || []
  } catch {
    ElMessage.warning('数据服务暂不可用')
  }
}

async function loadReports(targetPage = page.value) {
  page.value = targetPage
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize }
    if (filterType.value) params.report_type = filterType.value
    const data = await api.get<Paged<ReportItem>>('/reports', params)
    rows.value = data.list || []
    total.value = data.total || 0
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  createForm.report_type = 'daily'
  createForm.range = defaultRange()
  createForm.variety_ids = []
  createForm.region_ids = []
  createVisible.value = true
}

async function generateReport() {
  if (!createForm.range || createForm.range.length !== 2) {
    ElMessage.warning('请选择统计周期')
    return
  }
  creating.value = true
  try {
    const created = await api.post<GenerateResult>('/reports/generate', {
      report_type: createForm.report_type,
      period_start: createForm.range[0],
      period_end: createForm.range[1],
      variety_ids: createForm.variety_ids,
      region_ids: createForm.region_ids,
    })
    ElMessage.success('报告已生成')
    createVisible.value = false
    await loadReports(1)
    await openDetail(created.id)
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    creating.value = false
  }
}

async function openDetail(id: number) {
  drawerVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await api.get<ReportDetail>(`/reports/${id}`)
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    detailLoading.value = false
  }
}

async function downloadReport(row: { id: number; title: string }, format: 'html' | 'md') {
  const ext = format === 'md' ? 'md' : 'html'
  try {
    await api.download(`/reports/${row.id}/download`, { format }, `${row.title || 'report'}.${ext}`)
  } catch {
    ElMessage.warning('数据服务暂不可用')
  }
}

function downloadDetail(format: 'html' | 'md') {
  if (!detail.value) return
  downloadReport(detail.value, format)
}

async function removeReport(row: ReportItem) {
  try {
    await ElMessageBox.confirm(`确认删除报告「${row.title}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await api.delete(`/reports/${row.id}`)
    ElMessage.success('已删除')
    if (detail.value?.id === row.id) drawerVisible.value = false
    await loadReports(rows.value.length === 1 && page.value > 1 ? page.value - 1 : page.value)
  } catch {
    ElMessage.warning('数据服务暂不可用')
  }
}

onMounted(() => {
  loadMeta()
  loadReports(1)
})
</script>

<style scoped>
.form-tip {
  padding-left: 88px;
  font-size: 12px;
}

.report-detail {
  min-height: 240px;
}

.report-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  margin-bottom: 16px;
  padding: 10px 14px;
  font-size: 13px;
  color: #5b6b7f;
  background: #f7f9fd;
  border-radius: 8px;
}

.report-content {
  padding: 4px 6px 24px;
  font-size: 14px;
  line-height: 1.75;
  color: #2a3a4d;
  word-break: break-word;
}

.report-content :deep(h1) {
  margin: 0 0 14px;
  font-size: 22px;
  color: #16233a;
}

.report-content :deep(h2) {
  margin: 22px 0 10px;
  padding-bottom: 6px;
  font-size: 18px;
  color: #1c2a3a;
  border-bottom: 1px solid #e4e9f2;
}

.report-content :deep(h3) {
  margin: 16px 0 8px;
  font-size: 15px;
  color: #1f5fd6;
}

.report-content :deep(p) {
  margin: 8px 0;
}

.report-content :deep(ul),
.report-content :deep(ol) {
  padding-left: 22px;
}

.report-content :deep(table) {
  width: 100%;
  margin: 12px 0;
  border-collapse: collapse;
  font-size: 13px;
}

.report-content :deep(th),
.report-content :deep(td) {
  padding: 7px 10px;
  text-align: left;
  border: 1px solid #e4e9f2;
}

.report-content :deep(th) {
  font-weight: 600;
  color: #40536b;
  background: #f7f9fd;
}

.report-content :deep(blockquote) {
  margin: 10px 0;
  padding: 8px 14px;
  color: #5b6b7f;
  background: #f7f9fd;
  border-left: 3px solid #1f5fd6;
}
</style>
