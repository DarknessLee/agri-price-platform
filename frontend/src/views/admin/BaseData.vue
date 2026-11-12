<template>
  <div class="page">
    <PageHeader title="基础数据" subtitle="维护价格监测涉及的品种与地区字典，停用后不再出现在业务下拉选项中">
      <template #actions>
        <el-button :icon="Refresh" :loading="loadingVarieties || loadingRegions" @click="loadAll">刷新</el-button>
      </template>
    </PageHeader>

    <div class="page-card">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane :label="`品种（${varieties.length}）`" name="variety">
          <div class="toolbar">
            <el-button type="primary" :icon="Plus" @click="openVarietyCreate">新增品种</el-button>
            <span class="muted grow" style="text-align: right">
              品种编码用于开放 API 参数，建议使用拼音或英文简称，如 pig、egg
            </span>
          </div>
          <el-table v-loading="loadingVarieties" :data="varieties" stripe border>
            <el-table-column prop="code" label="品种编码" width="140">
              <template #default="{ row }"><span class="mono">{{ row.code }}</span></template>
            </el-table-column>
            <el-table-column prop="name" label="品种名称" min-width="120" />
            <el-table-column prop="category" label="品类" width="110">
              <template #default="{ row }">
                <el-tag effect="plain" type="info">{{ row.category }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="unit" label="计量单位" width="110" />
            <el-table-column label="价格记录" width="110" align="right">
              <template #default="{ row }">
                <span class="mono">{{ fmtInt(row.record_count) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="启用状态" width="110" align="center">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.enabled"
                  :loading="row._switching"
                  inline-prompt
                  active-text="启用"
                  inactive-text="停用"
                  @change="(val: boolean | string | number) => toggleVariety(row, Boolean(val))"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="130" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openVarietyEdit(row)">编辑</el-button>
                <el-button link type="danger" @click="removeVariety(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无品种数据" />
            </template>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`地区（${regions.length}）`" name="region">
          <div class="toolbar">
            <el-button type="primary" :icon="Plus" @click="openRegionCreate">新增地区</el-button>
            <span class="muted grow" style="text-align: right">
              地区编码建议使用行政区划代码，如 110000 表示北京市
            </span>
          </div>
          <el-table v-loading="loadingRegions" :data="regions" stripe border>
            <el-table-column prop="code" label="地区编码" width="150">
              <template #default="{ row }"><span class="mono">{{ row.code }}</span></template>
            </el-table-column>
            <el-table-column prop="name" label="地区名称" min-width="140" />
            <el-table-column prop="level" label="行政级别" width="120">
              <template #default="{ row }">
                <el-tag effect="plain" type="info">{{ row.level }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="价格记录" width="110" align="right">
              <template #default="{ row }">
                <span class="mono">{{ fmtInt(row.record_count) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="启用状态" width="110" align="center">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.enabled"
                  :loading="row._switching"
                  inline-prompt
                  active-text="启用"
                  inactive-text="停用"
                  @change="(val: boolean | string | number) => toggleRegion(row, Boolean(val))"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="130" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openRegionEdit(row)">编辑</el-button>
                <el-button link type="danger" @click="removeRegion(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无地区数据" />
            </template>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog
      v-model="varietyVisible"
      :title="varietyEditingId ? '编辑品种' : '新增品种'"
      width="520px"
      destroy-on-close
      @opened="varietyFormRef?.clearValidate()"
    >
      <el-form ref="varietyFormRef" :model="varietyForm" :rules="varietyRules" label-width="92px">
        <el-form-item label="品种编码" prop="code">
          <el-input v-model="varietyForm.code" placeholder="仅字母、数字、下划线，如 pig" maxlength="32" />
        </el-form-item>
        <el-form-item label="品种名称" prop="name">
          <el-input v-model="varietyForm.name" placeholder="如：生猪" maxlength="64" />
        </el-form-item>
        <el-form-item label="所属品类" prop="category">
          <el-select v-model="varietyForm.category" placeholder="请选择或输入品类" filterable allow-create default-first-option style="width: 100%">
            <el-option v-for="item in categoryOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="计量单位" prop="unit">
          <el-select v-model="varietyForm.unit" placeholder="请选择或输入单位" filterable allow-create default-first-option style="width: 100%">
            <el-option v-for="item in unitOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch v-model="varietyForm.enabled" inline-prompt active-text="启用" inactive-text="停用" />
          <span class="muted" style="margin-left: 10px">停用后不参与新增价格录入</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="varietyVisible = false">取消</el-button>
        <el-button type="primary" :loading="varietySaving" @click="submitVariety">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="regionVisible"
      :title="regionEditingId ? '编辑地区' : '新增地区'"
      width="520px"
      destroy-on-close
      @opened="regionFormRef?.clearValidate()"
    >
      <el-form ref="regionFormRef" :model="regionForm" :rules="regionRules" label-width="92px">
        <el-form-item label="地区编码" prop="code">
          <el-input v-model="regionForm.code" placeholder="仅字母、数字、下划线，如 110000" maxlength="32" />
        </el-form-item>
        <el-form-item label="地区名称" prop="name">
          <el-input v-model="regionForm.name" placeholder="如：北京市" maxlength="64" />
        </el-form-item>
        <el-form-item label="行政级别" prop="level">
          <el-select v-model="regionForm.level" placeholder="请选择或输入级别" filterable allow-create default-first-option style="width: 100%">
            <el-option v-for="item in levelOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch v-model="regionForm.enabled" inline-prompt active-text="启用" inactive-text="停用" />
          <span class="muted" style="margin-left: 10px">停用后不参与新增价格录入</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="regionVisible = false">取消</el-button>
        <el-button type="primary" :loading="regionSaving" @click="submitRegion">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import api, { ApiError } from '@/api/client'
import { fmtInt } from '@/utils/format'

interface VarietyRow {
  id: number
  code: string
  name: string
  category?: string
  unit?: string
  enabled: boolean
  record_count?: number
  _switching?: boolean
}

interface RegionRow {
  id: number
  code: string
  name: string
  level?: string
  enabled: boolean
  record_count?: number
  _switching?: boolean
}

const activeTab = ref<'variety' | 'region'>('variety')

const varieties = ref<VarietyRow[]>([])
const regions = ref<RegionRow[]>([])
const loadingVarieties = ref(false)
const loadingRegions = ref(false)

const categoryOptions = ['畜产品', '蔬菜', '水果', '粮油', '禽蛋']
const unitOptions = ['元/公斤', '元/斤', '元/只', '元/吨']
const levelOptions = ['省级', '市级', '县级']

const varietyVisible = ref(false)
const varietyEditingId = ref<number | null>(null)
const varietySaving = ref(false)
const varietyFormRef = ref<FormInstance>()
const varietyForm = reactive({
  code: '',
  name: '',
  category: '畜产品',
  unit: '元/公斤',
  enabled: true,
})

const regionVisible = ref(false)
const regionEditingId = ref<number | null>(null)
const regionSaving = ref(false)
const regionFormRef = ref<FormInstance>()
const regionForm = reactive({
  code: '',
  name: '',
  level: '省级',
  enabled: true,
})

const codePattern = /^[A-Za-z0-9_]+$/

const varietyRules: FormRules = {
  code: [
    { required: true, message: '请输入品种编码', trigger: 'blur' },
    { pattern: codePattern, message: '编码仅允许字母、数字和下划线', trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入品种名称', trigger: 'blur' }],
  category: [{ required: true, message: '请选择所属品类', trigger: 'change' }],
  unit: [{ required: true, message: '请选择计量单位', trigger: 'change' }],
}

const regionRules: FormRules = {
  code: [
    { required: true, message: '请输入地区编码', trigger: 'blur' },
    { pattern: codePattern, message: '编码仅允许字母、数字和下划线', trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入地区名称', trigger: 'blur' }],
  level: [{ required: true, message: '请选择行政级别', trigger: 'change' }],
}

function errorOf(err: unknown): string {
  if (err instanceof ApiError) return err.message
  const payload = (err as { response?: { data?: { message?: string } } })?.response?.data
  return payload?.message || ''
}

function warn(err: unknown) {
  const message = errorOf(err)
  ElMessage.warning(message && message !== 'Network Error' ? message : '数据服务暂不可用')
}

function statusOf(err: unknown): number | undefined {
  return (err as { response?: { status?: number } })?.response?.status
}

async function loadVarieties() {
  loadingVarieties.value = true
  try {
    const list = await api.get<VarietyRow[]>('/admin/varieties')
    varieties.value = list || []
  } catch (err) {
    varieties.value = []
    warn(err)
  } finally {
    loadingVarieties.value = false
  }
}

async function loadRegions() {
  loadingRegions.value = true
  try {
    const list = await api.get<RegionRow[]>('/admin/regions')
    regions.value = list || []
  } catch (err) {
    regions.value = []
    warn(err)
  } finally {
    loadingRegions.value = false
  }
}

async function loadAll() {
  await Promise.all([loadVarieties(), loadRegions()])
}

function handleTabChange() {
  if (activeTab.value === 'variety' && !varieties.value.length) loadVarieties()
  if (activeTab.value === 'region' && !regions.value.length) loadRegions()
}

function openVarietyCreate() {
  varietyEditingId.value = null
  Object.assign(varietyForm, { code: '', name: '', category: '畜产品', unit: '元/公斤', enabled: true })
  varietyVisible.value = true
}

function openVarietyEdit(row: VarietyRow) {
  varietyEditingId.value = row.id
  Object.assign(varietyForm, {
    code: row.code,
    name: row.name,
    category: row.category || '畜产品',
    unit: row.unit || '元/公斤',
    enabled: Boolean(row.enabled),
  })
  varietyVisible.value = true
}

async function submitVariety() {
  const valid = await varietyFormRef.value?.validate().catch(() => false)
  if (!valid) return
  const duplicate = varieties.value.some(
    (item) => item.code.toLowerCase() === varietyForm.code.trim().toLowerCase() && item.id !== varietyEditingId.value,
  )
  if (duplicate) {
    ElMessage.warning('品种编码已存在，请更换')
    return
  }
  varietySaving.value = true
  try {
    const payload = {
      code: varietyForm.code.trim(),
      name: varietyForm.name.trim(),
      category: varietyForm.category,
      unit: varietyForm.unit,
      enabled: varietyForm.enabled,
    }
    if (varietyEditingId.value) {
      await api.put(`/admin/varieties/${varietyEditingId.value}`, payload)
      ElMessage.success('品种信息已更新')
    } else {
      await api.post('/admin/varieties', payload)
      ElMessage.success('品种已新增')
    }
    varietyVisible.value = false
    await loadVarieties()
  } catch (err) {
    warn(err)
  } finally {
    varietySaving.value = false
  }
}

async function toggleVariety(row: VarietyRow, enabled: boolean) {
  row.enabled = enabled
  row._switching = true
  try {
    await api.put(`/admin/varieties/${row.id}`, { enabled })
    ElMessage.success(`品种「${row.name}」已${enabled ? '启用' : '停用'}`)
  } catch (err) {
    row.enabled = !enabled
    warn(err)
  } finally {
    row._switching = false
  }
}

async function removeVariety(row: VarietyRow) {
  try {
    await ElMessageBox.confirm(
      `确认删除品种「${row.name}」？该品种已有 ${row.record_count ?? 0} 条价格记录，删除后相关记录将失去字典关联。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    try {
      await api.delete(`/admin/varieties/${row.id}`)
      ElMessage.success('品种已删除')
    } catch (err) {
      const status = statusOf(err)
      if (status === 404 || status === 405 || status === 501) {
        await api.put(`/admin/varieties/${row.id}`, { enabled: false })
        ElMessage.success(`当前接口不支持物理删除，品种「${row.name}」已停用`)
      } else {
        throw err
      }
    }
    await loadVarieties()
  } catch (err) {
    warn(err)
  }
}

function openRegionCreate() {
  regionEditingId.value = null
  Object.assign(regionForm, { code: '', name: '', level: '省级', enabled: true })
  regionVisible.value = true
}

function openRegionEdit(row: RegionRow) {
  regionEditingId.value = row.id
  Object.assign(regionForm, {
    code: row.code,
    name: row.name,
    level: row.level || '省级',
    enabled: Boolean(row.enabled),
  })
  regionVisible.value = true
}

async function submitRegion() {
  const valid = await regionFormRef.value?.validate().catch(() => false)
  if (!valid) return
  const duplicate = regions.value.some(
    (item) => item.code.toLowerCase() === regionForm.code.trim().toLowerCase() && item.id !== regionEditingId.value,
  )
  if (duplicate) {
    ElMessage.warning('地区编码已存在，请更换')
    return
  }
  regionSaving.value = true
  try {
    const payload = {
      code: regionForm.code.trim(),
      name: regionForm.name.trim(),
      level: regionForm.level,
      enabled: regionForm.enabled,
    }
    if (regionEditingId.value) {
      await api.put(`/admin/regions/${regionEditingId.value}`, payload)
      ElMessage.success('地区信息已更新')
    } else {
      await api.post('/admin/regions', payload)
      ElMessage.success('地区已新增')
    }
    regionVisible.value = false
    await loadRegions()
  } catch (err) {
    warn(err)
  } finally {
    regionSaving.value = false
  }
}

async function toggleRegion(row: RegionRow, enabled: boolean) {
  row.enabled = enabled
  row._switching = true
  try {
    await api.put(`/admin/regions/${row.id}`, { enabled })
    ElMessage.success(`地区「${row.name}」已${enabled ? '启用' : '停用'}`)
  } catch (err) {
    row.enabled = !enabled
    warn(err)
  } finally {
    row._switching = false
  }
}

async function removeRegion(row: RegionRow) {
  try {
    await ElMessageBox.confirm(
      `确认删除地区「${row.name}」？该地区已有 ${row.record_count ?? 0} 条价格记录，删除后相关记录将失去字典关联。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    try {
      await api.delete(`/admin/regions/${row.id}`)
      ElMessage.success('地区已删除')
    } catch (err) {
      const status = statusOf(err)
      if (status === 404 || status === 405 || status === 501) {
        await api.put(`/admin/regions/${row.id}`, { enabled: false })
        ElMessage.success(`当前接口不支持物理删除，地区「${row.name}」已停用`)
      } else {
        throw err
      }
    }
    await loadRegions()
  } catch (err) {
    warn(err)
  }
}

onMounted(loadAll)
</script>

<style scoped>
.page :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.page :deep(.el-table) {
  font-size: 13px;
}
</style>
