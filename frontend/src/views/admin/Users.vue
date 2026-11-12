<template>
  <div class="page">
    <PageHeader title="用户管理" subtitle="维护平台登录账号、角色与联系方式，账号状态变更后即时生效">
      <template #actions>
        <el-button type="primary" :icon="Plus" @click="openCreate">新增用户</el-button>
      </template>
    </PageHeader>

    <div class="page-card">
      <div class="toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索用户名 / 姓名 / 机构 / 手机 / 邮箱"
          clearable
          style="width: 320px"
          @keyup.enter="search"
          @clear="search"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="resetSearch">重置</el-button>
        <span class="muted grow" style="text-align: right">共 {{ fmtInt(total) }} 个账号</span>
      </div>

      <el-table v-loading="loading" :data="rows" stripe border>
        <el-table-column prop="username" label="用户名" min-width="150">
          <template #default="{ row }">
            <span class="mono">{{ row.username }}</span>
            <el-tag v-if="isSelf(row)" size="small" effect="plain" style="margin-left: 6px">当前账号</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="display_name" label="姓名" min-width="90" />
        <el-table-column label="角色" min-width="110">
          <template #default="{ row }">
            <el-tag effect="plain">{{ row.role_name || row.role_key }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="org" label="所属机构" min-width="140" show-overflow-tooltip />
        <el-table-column prop="phone" label="手机号" width="125" />
        <el-table-column prop="email" label="邮箱" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="88" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === '启用' ? 'success' : 'info'" effect="light">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" width="165">
          <template #default="{ row }">
            <span class="muted">{{ fmtDateTime(row.last_login_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" :disabled="isSelf(row)" @click="toggleStatus(row)">
              {{ row.status === '启用' ? '停用' : '启用' }}
            </el-button>
            <el-button link type="primary" @click="openReset(row)">重置密码</el-button>
            <el-button link type="danger" :disabled="isSelf(row)" @click="confirmDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无用户数据" />
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

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑用户' : '新增用户'"
      width="580px"
      destroy-on-close
      @opened="formRef?.clearValidate()"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="Boolean(editingId)" placeholder="3-32 位字母、数字或 _ . -" maxlength="32" />
        </el-form-item>
        <el-form-item v-if="!editingId" label="初始密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="不少于 8 位" maxlength="32" />
        </el-form-item>
        <el-form-item label="姓名" prop="display_name">
          <el-input v-model="form.display_name" placeholder="如：张明" maxlength="64" />
        </el-form-item>
        <el-form-item label="角色" prop="role_key">
          <el-select v-model="form.role_key" placeholder="请选择角色" style="width: 100%" :disabled="Boolean(editingId) && editingId === currentId">
            <el-option v-for="item in roles" :key="item.key" :label="item.name" :value="item.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属机构" prop="org">
          <el-input v-model="form.org" placeholder="如：市场监测部" maxlength="128" />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="form.phone" placeholder="11 位手机号" maxlength="11" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="name@example.com" maxlength="128" />
        </el-form-item>
        <el-form-item v-if="editingId" label="状态" prop="status">
          <el-radio-group v-model="form.status" :disabled="editingId === currentId">
            <el-radio value="启用">启用</el-radio>
            <el-radio value="停用">停用</el-radio>
          </el-radio-group>
          <span v-if="editingId === currentId" class="muted" style="margin-left: 10px">不能停用当前登录账号</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resetVisible" title="重置登录密码" width="440px" destroy-on-close @opened="resetFormRef?.clearValidate()">
      <el-form ref="resetFormRef" :model="resetForm" :rules="resetRules" label-width="92px">
        <el-form-item label="账号">
          <span class="mono">{{ resetTarget?.username }}</span>
        </el-form-item>
        <el-form-item label="新密码" prop="password">
          <el-input v-model="resetForm.password" type="password" show-password placeholder="不少于 8 位" maxlength="32" />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm">
          <el-input v-model="resetForm.confirm" type="password" show-password placeholder="请再次输入新密码" maxlength="32" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="submitReset">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import api, { ApiError, type Paged } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { fmtDateTime, fmtInt } from '@/utils/format'

interface AdminUser {
  id: number
  username: string
  display_name: string
  role_key: string
  role_name?: string
  org?: string
  phone?: string
  email?: string
  status?: string
  last_login_at?: string | null
}

interface RoleOption {
  key: string
  name: string
}

const auth = useAuthStore()
const currentId = computed(() => auth.user?.id)

const rows = ref<AdminUser[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const loading = ref(false)
const roles = ref<RoleOption[]>([])

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({
  username: '',
  password: '',
  display_name: '',
  role_key: 'viewer',
  org: '',
  phone: '',
  email: '',
  status: '启用',
})

const resetVisible = ref(false)
const resetting = ref(false)
const resetTarget = ref<AdminUser | null>(null)
const resetFormRef = ref<FormInstance>()
const resetForm = reactive({ password: '', confirm: '' })

const rules = computed<FormRules>(() => {
  const base: FormRules = {
    username: [
      { required: true, message: '请输入用户名', trigger: 'blur' },
      { pattern: /^[A-Za-z0-9_.-]{3,32}$/, message: '用户名需 3-32 位，仅支持字母、数字、下划线、点和短横线', trigger: 'blur' },
    ],
    role_key: [{ required: true, message: '请选择角色', trigger: 'change' }],
    phone: [
      {
        validator: (_rule, value, callback) => {
          if (!value) return callback()
          if (!/^1\d{10}$/.test(String(value))) return callback(new Error('请输入 11 位手机号'))
          callback()
        },
        trigger: 'blur',
      },
    ],
    email: [
      {
        validator: (_rule, value, callback) => {
          if (!value) return callback()
          if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value))) return callback(new Error('邮箱格式不正确'))
          callback()
        },
        trigger: 'blur',
      },
    ],
  }
  if (!editingId.value) {
    base.password = [
      { required: true, message: '请输入初始密码', trigger: 'blur' },
      { min: 8, message: '密码长度不能少于 8 位', trigger: 'blur' },
    ]
  }
  return base
})

const resetRules: FormRules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码长度不能少于 8 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== resetForm.password) return callback(new Error('两次输入的密码不一致'))
        callback()
      },
      trigger: 'blur',
    },
  ],
}

function isSelf(row: AdminUser): boolean {
  return currentId.value === row.id
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

async function load() {
  loading.value = true
  try {
    const res = await api.get<Paged<AdminUser>>('/users', {
      keyword: keyword.value.trim() || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    rows.value = res.list || []
    total.value = res.total || 0
  } catch (err) {
    rows.value = []
    total.value = 0
    warn(err)
  } finally {
    loading.value = false
  }
}

async function loadRoles() {
  try {
    const dicts = await api.get<{ roles?: RoleOption[] }>('/meta/dicts')
    if (Array.isArray(dicts?.roles) && dicts.roles.length) {
      roles.value = dicts.roles
      return
    }
  } catch {
    // 字典接口不可用时退回角色列表
  }
  try {
    const list = await api.get<Array<{ key: string; name: string }>>('/roles')
    if (list?.length) {
      roles.value = list.map((item) => ({ key: item.key, name: item.name }))
      return
    }
  } catch {
    // 角色权限不足时使用内置兜底
  }
  roles.value = [
    { key: 'admin', name: '系统管理员' },
    { key: 'analyst', name: '价格分析师' },
    { key: 'operator', name: '监测员' },
    { key: 'viewer', name: '领导/访客' },
  ]
}

function search() {
  page.value = 1
  load()
}

function resetSearch() {
  keyword.value = ''
  page.value = 1
  load()
}

function handleSizeChange() {
  page.value = 1
  load()
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    username: '',
    password: '',
    display_name: '',
    role_key: 'viewer',
    org: '',
    phone: '',
    email: '',
    status: '启用',
  })
  dialogVisible.value = true
}

function openEdit(row: AdminUser) {
  editingId.value = row.id
  Object.assign(form, {
    username: row.username,
    password: '',
    display_name: row.display_name || '',
    role_key: row.role_key,
    org: row.org || '',
    phone: row.phone || '',
    email: row.email || '',
    status: row.status || '启用',
  })
  dialogVisible.value = true
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    if (editingId.value) {
      await api.put(`/users/${editingId.value}`, {
        display_name: form.display_name,
        role_key: form.role_key,
        org: form.org,
        phone: form.phone,
        email: form.email,
        status: form.status,
      })
      ElMessage.success('用户信息已更新')
    } else {
      await api.post('/users', {
        username: form.username,
        password: form.password,
        display_name: form.display_name,
        role_key: form.role_key,
        org: form.org,
        phone: form.phone,
        email: form.email,
      })
      ElMessage.success('用户已创建')
    }
    dialogVisible.value = false
    await load()
  } catch (err) {
    warn(err)
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: AdminUser) {
  const target = row.status === '启用' ? '停用' : '启用'
  if (target === '停用') {
    try {
      await ElMessageBox.confirm(`确认停用账号「${row.username}」？停用后该账号将无法登录系统。`, '停用确认', {
        type: 'warning',
        confirmButtonText: '确认停用',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  try {
    try {
      await api.post(`/users/${row.id}/toggle`)
    } catch (err) {
      const status = statusOf(err)
      if (status === 404 || status === 405 || status === 501) {
        await api.put(`/users/${row.id}`, { status: target })
      } else {
        throw err
      }
    }
    ElMessage.success(`账号「${row.username}」已${target}`)
    await load()
  } catch (err) {
    warn(err)
  }
}

function openReset(row: AdminUser) {
  resetTarget.value = row
  resetForm.password = ''
  resetForm.confirm = ''
  resetVisible.value = true
}

async function submitReset() {
  const valid = await resetFormRef.value?.validate().catch(() => false)
  if (!valid || !resetTarget.value) return
  resetting.value = true
  try {
    await api.post(`/users/${resetTarget.value.id}/reset-password`, { password: resetForm.password })
    ElMessage.success(`账号「${resetTarget.value.username}」的密码已重置`)
    resetVisible.value = false
  } catch (err) {
    warn(err)
  } finally {
    resetting.value = false
  }
}

async function confirmDelete(row: AdminUser) {
  try {
    await ElMessageBox.confirm(`确认删除账号「${row.username}」？删除后不可恢复。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await api.delete(`/users/${row.id}`)
    ElMessage.success('用户已删除')
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (err) {
    warn(err)
  }
}

onMounted(async () => {
  await Promise.all([loadRoles(), load()])
})
</script>

<style scoped>
.page :deep(.el-table) {
  font-size: 13px;
}
</style>
