<template>
  <div class="page">
    <PageHeader title="操作审计" subtitle="记录平台关键操作行为，支持按账号、动作与时间范围追溯">
      <template #actions>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <div class="page-card">
      <div class="toolbar">
        <el-input
          v-model="filters.username"
          placeholder="用户名"
          clearable
          style="width: 160px"
          @keyup.enter="search"
          @clear="search"
        />
        <el-input
          v-model="filters.action"
          placeholder="操作动作，如：登录"
          clearable
          style="width: 180px"
          @keyup.enter="search"
          @clear="search"
        />
        <el-select v-model="filters.module" placeholder="业务模块" clearable style="width: 150px" @change="search">
          <el-option v-for="item in moduleOptions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          unlink-panels
          style="width: 260px"
          @change="search"
        />
        <el-button type="primary" :icon="Search" @click="search">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <span class="muted grow" style="text-align: right">共 {{ fmtInt(total) }} 条记录</span>
      </div>

      <el-table v-loading="loading" :data="rows" stripe border>
        <el-table-column label="操作时间" width="168">
          <template #default="{ row }">
            <span class="mono">{{ fmtDateTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="username" label="操作用户" width="120">
          <template #default="{ row }">
            <el-icon style="vertical-align: -2px; margin-right: 4px"><User /></el-icon>{{ row.username }}
          </template>
        </el-table-column>
        <el-table-column label="动作" width="128">
          <template #default="{ row }">
            <el-tag :type="actionTagType(row.action)" effect="light" size="small">{{ row.action }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="模块" width="100">
          <template #default="{ row }">
            <el-tag type="info" effect="plain" size="small">{{ row.module || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="detail" label="操作对象 / 详情" min-width="300" show-overflow-tooltip />
        <el-table-column label="IP 地址" width="130">
          <template #default="{ row }">
            <span class="mono muted">{{ row.ip || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="结果" width="88" align="center">
          <template #default="{ row }">
            <el-tag :type="resultOf(row).type" size="small">{{ resultOf(row).text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无审计日志" />
        </template>
      </el-table>

      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="load"
          @size-change="handleSizeChange"
        />
      </div>
    </div>

    <el-dialog v-model="detailVisible" title="审计日志详情" width="640px">
      <el-descriptions v-if="currentLog" :column="2" border size="small">
        <el-descriptions-item label="操作时间" :span="2">
          <span class="mono">{{ fmtDateTime(currentLog.created_at) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="操作用户">{{ currentLog.username }}</el-descriptions-item>
        <el-descriptions-item label="业务模块">{{ currentLog.module || '—' }}</el-descriptions-item>
        <el-descriptions-item label="操作动作">
          <el-tag :type="actionTagType(currentLog.action)" size="small">{{ currentLog.action }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="IP 地址">
          <span class="mono">{{ currentLog.ip || '—' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="操作详情" :span="2">
          <pre class="detail-pre mono">{{ prettyDetail }}</pre>
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button type="primary" @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search, User } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import api, { ApiError, type Paged } from '@/api/client'
import { fmtDateTime, fmtInt } from '@/utils/format'

interface AuditLogRow {
  id: number
  username: string
  action: string
  module: string
  detail: string
  ip?: string
  created_at?: string
}

const moduleOptions = ['认证', '监测', '预测', '预警', '情景', '报告', '治理', '后台', '基础数据']

const filters = reactive({ username: '', action: '', module: '' })
const dateRange = ref<[string, string] | null>(null)
const rows = ref<AuditLogRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const detailVisible = ref(false)
const currentLog = ref<AuditLogRow | null>(null)

const prettyDetail = computed(() => {
  const detail = currentLog.value?.detail || ''
  if (!detail) return '无详情'
  try {
    const parsed = JSON.parse(detail)
    return JSON.stringify(parsed, null, 2)
  } catch {
    return detail
  }
})

function errorOf(err: unknown): string {
  if (err instanceof ApiError) return err.message
  const payload = (err as { response?: { data?: { message?: string } } })?.response?.data
  return payload?.message || ''
}

function warn(err: unknown) {
  const message = errorOf(err)
  ElMessage.warning(message && message !== 'Network Error' ? message : '数据服务暂不可用')
}

function actionTagType(action?: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  if (!action) return 'info'
  if (['登录', '退出'].includes(action)) return 'info'
  if (['删除', '停用', '重置密码'].includes(action)) return 'danger'
  if (['新增', '导入数据', '生成报告'].includes(action)) return 'success'
  if (['编辑', '配置权限', '启停任务', '执行任务', '任务调度'].includes(action)) return 'warning'
  return 'primary'
}

function resultOf(row: AuditLogRow): { text: string; type: 'success' | 'danger' } {
  const detail = row.detail || ''
  // 审计 detail 是业务描述，可能合法包含“异常/错误”等词，仅以明确的“失败”判定结果
  const failed = detail.includes('失败')
  return failed ? { text: '失败', type: 'danger' } : { text: '成功', type: 'success' }
}

function dayParams(): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  if (filters.username.trim()) params.username = filters.username.trim()
  if (filters.module) params.module = filters.module
  if (filters.action.trim()) params.action = filters.action.trim()
  if (dateRange.value?.length === 2) {
    params.start = dateRange.value[0]
    params.end = `${dateRange.value[1]} 23:59:59`
  }
  return params
}

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      ...dayParams(),
      page: page.value,
      page_size: pageSize.value,
    }
    if (filters.action.trim()) {
      // 契约接口以 username/module/start/end 为查询维度，动作筛选补充在返回结果上做二次过滤
      const res = await api.get<Paged<AuditLogRow>>('/audit-logs', { ...params, page: 1, page_size: 200 })
      const keyword = filters.action.trim()
      const filtered = (res.list || []).filter((item) => (item.action || '').includes(keyword))
      total.value = filtered.length
      const start = (page.value - 1) * pageSize.value
      rows.value = filtered.slice(start, start + pageSize.value)
    } else {
      const res = await api.get<Paged<AuditLogRow>>('/audit-logs', params)
      rows.value = res.list || []
      total.value = res.total || 0
    }
  } catch (err) {
    rows.value = []
    total.value = 0
    warn(err)
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function resetFilters() {
  filters.username = ''
  filters.action = ''
  filters.module = ''
  dateRange.value = null
  page.value = 1
  load()
}

function handleSizeChange() {
  page.value = 1
  load()
}

function openDetail(row: AuditLogRow) {
  currentLog.value = row
  detailVisible.value = true
}

onMounted(load)
</script>

<style scoped>
.detail-pre {
  margin: 0;
  padding: 10px 12px;
  max-height: 320px;
  overflow: auto;
  background: #f7f9fd;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.page :deep(.el-table) {
  font-size: 13px;
}
</style>
