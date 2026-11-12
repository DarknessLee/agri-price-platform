<template>
  <div class="page">
    <PageHeader title="预警规则" subtitle="配置价格异常触发条件，规则命中后自动生成预警信息">
      <template #actions>
        <el-tooltip :disabled="canRule" content="暂无预警规则管理权限" placement="bottom">
          <span>
            <el-button type="primary" :disabled="!canRule" @click="openCreate">新增规则</el-button>
          </span>
        </el-tooltip>
      </template>
    </PageHeader>

    <div class="page-card">
      <div class="card-title">
        <span>规则类型说明</span>
        <span class="muted panel-hint">规则启用后，系统每次扫描时自动判断是否触发预警</span>
      </div>
      <div class="rule-type-grid">
        <div v-for="item in RULE_TYPES" :key="item.value" class="rule-type-item">
          <div class="rule-type-name">{{ item.label }}</div>
          <div class="muted rule-type-desc">{{ item.desc }}</div>
        </div>
      </div>
    </div>

    <div class="page-card">
      <div class="flex-between list-head">
        <div class="card-title list-title"><span>规则列表</span></div>
        <div class="toolbar list-toolbar">
          <span class="muted rule-count">共 {{ rules.length }} 条规则，启用 {{ enabledCount }} 条</span>
          <el-button :loading="loading" @click="loadRules">刷新</el-button>
        </div>
      </div>

      <el-table :data="rules" size="small" stripe max-height="600" v-loading="loading">
        <el-table-column label="规则名称" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="rule-name">{{ row.name }}</div>
            <div v-if="row.created_at" class="muted rule-sub">创建于 {{ fmtDateTime(row.created_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="品种" min-width="88" show-overflow-tooltip>
          <template #default="{ row }">{{ row.variety || '全部品种' }}</template>
        </el-table-column>
        <el-table-column label="地区" min-width="96" show-overflow-tooltip>
          <template #default="{ row }">{{ row.region || '全部地区' }}</template>
        </el-table-column>
        <el-table-column label="规则类型" width="104">
          <template #default="{ row }">
            <el-tag type="info" size="small" effect="plain">{{ typeLabel(row.rule_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发条件" min-width="156">
          <template #default="{ row }">
            {{ operatorLabel(row.operator) }} {{ fmtNum(row.threshold, 2) }}，窗口 {{ row.window_days }} 天
          </template>
        </el-table-column>
        <el-table-column label="级别" width="82" align="center">
          <template #default="{ row }">
            <el-tag :type="levelTagType(row.level)" size="small" effect="dark">{{ row.level }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="通知渠道" min-width="132" show-overflow-tooltip>
          <template #default="{ row }">{{ channelText(row.channel) }}</template>
        </el-table-column>
        <el-table-column label="命中次数" width="92" align="right">
          <template #default="{ row }">{{ fmtInt(row.hit_count) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="104" align="center">
          <template #default="{ row }">
            <el-tooltip :disabled="canRule" content="暂无预警规则管理权限" placement="top">
              <span class="switch-wrap">
                <el-switch
                  :model-value="row.enabled"
                  :loading="toggleId === row.id"
                  :disabled="!canRule"
                  @change="toggleRule(row)"
                />
              </span>
            </el-tooltip>
            <span class="switch-text" :class="{ 'is-on': row.enabled }">{{ row.enabled ? '启用' : '停用' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" :disabled="!canRule" @click="openEdit(row)">编辑</el-button>
            <el-button
              link
              type="danger"
              size="small"
              :disabled="!canRule"
              :loading="deletingId === row.id"
              @click="removeRule(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无预警规则，点击“新增规则”进行配置" :image-size="64" />
        </template>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑预警规则' : '新增预警规则'"
      width="640px"
      top="6vh"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="96px">
        <el-form-item label="规则名称" prop="name">
          <el-input v-model="form.name" maxlength="40" show-word-limit placeholder="例如：苹果价格突破阈值提醒" />
        </el-form-item>
        <el-row :gutter="14">
          <el-col :span="12">
            <el-form-item label="品种" prop="variety_id">
              <el-select v-model="form.variety_id" filterable placeholder="请选择品种" style="width: 100%">
                <el-option
                  v-for="item in dicts?.varieties || []"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="地区">
              <el-select v-model="form.region_id" clearable filterable placeholder="全部地区" style="width: 100%">
                <el-option
                  v-for="item in dicts?.regions || []"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="14">
          <el-col :span="12">
            <el-form-item label="规则类型" prop="rule_type">
              <el-select v-model="form.rule_type" style="width: 100%" @change="onRuleTypeChange">
                <el-option v-for="item in RULE_TYPES" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="比较方式" prop="operator">
              <el-select v-model="form.operator" style="width: 100%">
                <el-option v-for="item in OPERATORS" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="14">
          <el-col :span="12">
            <el-form-item label="阈值" prop="threshold">
              <el-input-number
                v-model="form.threshold"
                :min="0.01"
                :step="1"
                :precision="2"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="统计窗口" prop="window_days">
              <el-input-number
                v-model="form.window_days"
                :min="1"
                :max="365"
                :step="1"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="14">
          <el-col :span="12">
            <el-form-item label="预警级别" prop="level">
              <el-select v-model="form.level" style="width: 100%">
                <el-option v-for="item in levelOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="通知渠道">
              <el-select v-model="form.channel" multiple collapse-tags style="width: 100%">
                <el-option v-for="item in CHANNELS" :key="item" :label="item" :value="item" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="启用状态">
          <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <div class="rule-desc">
        <span class="rule-desc-label">规则说明：</span>{{ selectedTypeDesc }}
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import api from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { fmtDateTime, fmtInt, fmtNum, levelTagType } from '@/utils/format'
import type { MetaDicts } from '@/types'

interface RuleRow {
  id: number
  name: string
  variety_id?: number | null
  variety?: string
  region_id?: number | null
  region?: string
  rule_type: string
  rule_type_name?: string
  operator: string
  threshold: number
  window_days: number
  level: string
  enabled: boolean
  channel?: string
  hit_count?: number
  created_at?: string
}

interface RuleForm {
  name: string
  variety_id: number | null
  region_id: number | null
  rule_type: string
  operator: string
  threshold: number
  window_days: number
  level: string
  enabled: boolean
  channel: string[]
}

const RULE_TYPES = [
  { value: 'price_threshold', label: '价格阈值', desc: '监测价格高于或低于设定阈值时触发预警' },
  { value: 'volatility', label: '波动率', desc: '统计窗口内价格波动幅度超过设定阈值时触发预警' },
  { value: 'yoy', label: '同比', desc: '价格同比涨跌幅超过设定阈值时触发预警' },
  { value: 'spread', label: '价差', desc: '同品种跨地区价格差超过设定阈值时触发预警' },
]

const OPERATORS = [
  { value: 'gt', label: '高于' },
  { value: 'lt', label: '低于' },
  { value: 'gte', label: '不低于' },
  { value: 'lte', label: '不高于' },
  { value: 'abs_gt', label: '绝对波动超' },
]

const CHANNELS = ['站内消息', '短信', '邮件', '微信']

const auth = useAuthStore()
const canRule = computed(() => auth.hasPerm('alert:rule'))

const dicts = ref<MetaDicts | null>(null)
const rules = ref<RuleRow[]>([])
const loading = ref(false)
const saving = ref(false)
const toggleId = ref<number | null>(null)
const deletingId = ref<number | null>(null)

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()

const form = reactive<RuleForm>(defaultForm())

const levelOptions = computed(() => {
  const levels = dicts.value?.alert_levels || []
  return levels.length ? levels : ['高', '中', '低']
})

const enabledCount = computed(() => rules.value.filter((item) => item.enabled).length)

const selectedTypeDesc = computed(() => {
  const item = RULE_TYPES.find((type) => type.value === form.rule_type)
  return item?.desc || '请选择规则类型'
})

const formRules: FormRules = {
  name: [{ required: true, message: '请输入规则名称', trigger: 'blur' }],
  variety_id: [{ required: true, message: '请选择品种', trigger: 'change' }],
  rule_type: [{ required: true, message: '请选择规则类型', trigger: 'change' }],
  operator: [{ required: true, message: '请选择比较方式', trigger: 'change' }],
  threshold: [
    {
      validator: (_rule, value, callback) => {
        const num = Number(value)
        if (!Number.isFinite(num) || num <= 0) {
          callback(new Error('阈值必须为大于 0 的数字'))
          return
        }
        callback()
      },
      trigger: 'change',
    },
  ],
  window_days: [
    {
      validator: (_rule, value, callback) => {
        const num = Number(value)
        if (!Number.isInteger(num) || num < 1 || num > 365) {
          callback(new Error('统计窗口需为 1-365 之间的整数'))
          return
        }
        callback()
      },
      trigger: 'change',
    },
  ],
}

function defaultForm(): RuleForm {
  return {
    name: '',
    variety_id: null,
    region_id: null,
    rule_type: 'price_threshold',
    operator: 'gt',
    threshold: 10,
    window_days: 7,
    level: '中',
    enabled: true,
    channel: ['站内消息'],
  }
}

function typeLabel(value?: string): string {
  const item = RULE_TYPES.find((type) => type.value === value)
  return item?.label || value || '—'
}

function operatorLabel(value?: string): string {
  const item = OPERATORS.find((operator) => operator.value === value)
  return item?.label || value || '—'
}

function parseChannel(channel?: string): string[] {
  if (!channel) return ['站内消息']
  const text = String(channel).trim()
  if (!text) return ['站内消息']
  if (text.startsWith('[')) {
    try {
      const parsed = JSON.parse(text)
      if (Array.isArray(parsed)) {
        const names = parsed.map((item) => String(item)).filter(Boolean)
        return names.length ? names : ['站内消息']
      }
    } catch {
      /* 非 JSON 渠道按普通文本处理 */
    }
  }
  const names = text
    .replace(/，/g, ',')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  return names.length ? names : ['站内消息']
}

function channelText(channel?: string): string {
  return parseChannel(channel).join('、')
}

function resetForm() {
  editingId.value = null
  Object.assign(form, defaultForm())
  formRef.value?.clearValidate()
}

async function loadDicts() {
  dicts.value = await api.get<MetaDicts>('/meta/dicts')
}

async function fetchRules() {
  rules.value = await api.get<RuleRow[]>('/alerts/rules')
}

async function loadRules() {
  loading.value = true
  try {
    await fetchRules()
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  if (!canRule.value) return
  editingId.value = null
  Object.assign(form, defaultForm())
  dialogVisible.value = true
  nextTick(() => formRef.value?.clearValidate())
}

function openEdit(row: RuleRow) {
  if (!canRule.value) return
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    variety_id: row.variety_id ?? null,
    region_id: row.region_id ?? null,
    rule_type: row.rule_type,
    operator: row.operator,
    threshold: Number(row.threshold),
    window_days: Number(row.window_days),
    level: row.level,
    enabled: Boolean(row.enabled),
    channel: parseChannel(row.channel),
  })
  dialogVisible.value = true
  nextTick(() => formRef.value?.clearValidate())
}

function onRuleTypeChange() {
  formRef.value?.clearValidate('threshold')
}

async function saveRule() {
  const formEl = formRef.value
  if (!formEl) return
  try {
    await formEl.validate()
  } catch {
    return
  }
  saving.value = true
  const payload = {
    name: form.name.trim(),
    variety_id: form.variety_id,
    region_id: form.region_id,
    rule_type: form.rule_type,
    operator: form.operator,
    threshold: Number(form.threshold),
    window_days: Number(form.window_days),
    level: form.level,
    enabled: form.enabled,
    channel: form.channel.join(','),
  }
  try {
    if (editingId.value) {
      await api.put(`/alerts/rules/${editingId.value}`, payload)
      ElMessage.success('规则已更新')
    } else {
      await api.post('/alerts/rules', payload)
      ElMessage.success('规则已创建')
    }
    dialogVisible.value = false
    await fetchRules()
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    saving.value = false
  }
}

async function toggleRule(row: RuleRow) {
  if (!canRule.value) return
  toggleId.value = row.id
  try {
    await api.post(`/alerts/rules/${row.id}/toggle`)
    ElMessage.success(row.enabled ? '规则已停用' : '规则已启用')
    await fetchRules()
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    toggleId.value = null
  }
}

async function removeRule(row: RuleRow) {
  if (!canRule.value) return
  try {
    await ElMessageBox.confirm(`确认删除预警规则「${row.name}」？删除后不可恢复。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  deletingId.value = row.id
  try {
    await api.delete(`/alerts/rules/${row.id}`)
    ElMessage.success('规则已删除')
    await fetchRules()
  } catch {
    ElMessage.warning('数据服务暂不可用')
  } finally {
    deletingId.value = null
  }
}

onMounted(async () => {
  loading.value = true
  const results = await Promise.allSettled([loadDicts(), fetchRules()])
  loading.value = false
  if (results.some((item) => item.status === 'rejected')) {
    ElMessage.warning('数据服务暂不可用')
  }
})
</script>

<style scoped>
.panel-hint {
  font-size: 12px;
  font-weight: 400;
}

.rule-type-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

@media (max-width: 1100px) {
  .rule-type-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.rule-type-item {
  padding: 12px 14px;
  border-radius: 8px;
  background: #f7f9fd;
  border: 1px solid #e9eef7;
}

.rule-type-name {
  margin-bottom: 4px;
  font-size: 13px;
  font-weight: 600;
  color: #1f5fd6;
}

.rule-type-desc {
  font-size: 12px;
  line-height: 1.6;
}

.list-head {
  margin-bottom: 14px;
}

.list-title {
  margin: 0;
}

.list-toolbar {
  margin: 0;
}

.rule-count {
  font-size: 12px;
}

.rule-name {
  font-weight: 500;
  color: #1c2a3a;
}

.rule-sub {
  margin-top: 2px;
  font-size: 11px;
}

.switch-wrap {
  display: inline-block;
}

.switch-text {
  margin-left: 6px;
  font-size: 12px;
  color: #8b9aae;
}

.switch-text.is-on {
  color: #1c9c6b;
}

.rule-desc {
  margin-top: 4px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f2f7ff;
  font-size: 12px;
  line-height: 1.7;
  color: #5b6b7f;
}

.rule-desc-label {
  color: #1f5fd6;
  font-weight: 500;
}
</style>
