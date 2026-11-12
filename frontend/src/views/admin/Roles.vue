<template>
  <div class="page">
    <PageHeader title="角色权限" subtitle="按角色分配平台功能权限点，保存后对拥有该角色的账号即时生效">
      <template #actions>
        <el-button :icon="Refresh" :loading="loading" @click="reload">刷新</el-button>
      </template>
    </PageHeader>

    <div class="role-layout">
      <div class="page-card role-list">
        <div class="card-title"><span>角色列表</span><span class="muted" style="font-size: 12px">{{ roles.length }} 个角色</span></div>
        <div
          v-for="item in roles"
          :key="item.key"
          class="role-item"
          :class="{ active: selectedKey === item.key }"
          @click="selectRole(item)"
        >
          <div class="role-item-head">
            <div class="flex gap-8">
              <span class="role-avatar"><el-icon><UserFilled /></el-icon></span>
              <div>
                <div class="role-name">
                  {{ item.name }}
                  <el-tag v-if="item.key === 'admin'" size="small" type="warning" effect="plain" style="margin-left: 6px">内置</el-tag>
                </div>
                <div class="role-key mono">{{ item.key }}</div>
              </div>
            </div>
            <el-icon class="role-arrow"><ArrowRight /></el-icon>
          </div>
          <div class="role-desc">{{ item.description || '暂无角色描述' }}</div>
          <div class="role-stats">
            <span><el-icon><User /></el-icon> {{ fmtInt(item.user_count) }} 人</span>
            <span><el-icon><Key /></el-icon> {{ (item.permissions || []).length }} 项权限</span>
          </div>
        </div>
        <el-empty v-if="!loading && !roles.length" description="暂无角色数据" :image-size="70" />
        <div v-loading="loading" class="role-loading" v-show="loading"></div>
      </div>

      <div class="page-card perm-panel">
        <template v-if="selectedRole">
          <div class="card-title">
            <span>{{ selectedRole.name }} · 权限配置</span>
            <span class="muted" style="font-size: 12px">已选 {{ selectedPerms.length }} / {{ permissions.length }} 项</span>
          </div>

          <el-alert
            v-if="readonly"
            title="系统内置角色，权限固定"
            type="warning"
            :closable="false"
            show-icon
            description="系统管理员拥有平台全部权限，不支持调整；如需给其他账号授权，请为其分配相应角色。"
            style="margin-bottom: 14px"
          />

          <div v-if="permissions.length" class="perm-modules" :class="{ readonly }">
            <div v-for="group in groups" :key="group.module" class="perm-module">
              <div class="perm-module-head">
                <span class="perm-module-name">{{ group.module }}</span>
                <el-checkbox
                  :model-value="moduleAllChecked(group)"
                  :indeterminate="moduleIndeterminate(group)"
                  :disabled="readonly"
                  @change="(val: CheckboxValueType) => toggleModule(group, val)"
                >
                  全选
                </el-checkbox>
              </div>
              <el-checkbox-group v-model="selectedPerms" :disabled="readonly" class="perm-items">
                <el-checkbox v-for="perm in group.items" :key="perm.key" :value="perm.key">
                  <span class="perm-name">{{ perm.name }}</span>
                  <span class="perm-key mono">{{ perm.key }}</span>
                </el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
          <el-empty v-else-if="!loading" description="暂无权限点数据" />

          <div class="perm-footer">
            <span class="muted">提示：权限点调整后，相关账号重新进入页面即可生效。</span>
            <el-button type="primary" :disabled="readonly" :loading="saving" @click="save">保存权限</el-button>
          </div>
        </template>
        <el-empty v-else description="请选择左侧角色查看权限配置" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { CheckboxValueType } from 'element-plus'
import { ArrowRight, Key, Refresh, User, UserFilled } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import api, { ApiError } from '@/api/client'
import { fmtInt } from '@/utils/format'

interface RoleInfo {
  key: string
  name: string
  description?: string
  user_count?: number
  permissions?: string[]
}

interface PermissionItem {
  key: string
  name: string
  module?: string
}

interface PermissionGroup {
  module: string
  items: PermissionItem[]
}

const roles = ref<RoleInfo[]>([])
const permissions = ref<PermissionItem[]>([])
const selectedKey = ref('')
const selectedPerms = ref<string[]>([])
const loading = ref(false)
const saving = ref(false)

const groups = computed<PermissionGroup[]>(() => {
  const map = new Map<string, PermissionItem[]>()
  for (const item of permissions.value) {
    const module = item.module || '其他'
    const list = map.get(module) || []
    list.push(item)
    map.set(module, list)
  }
  return Array.from(map.entries()).map(([module, items]) => ({ module, items }))
})

const selectedRole = computed<RoleInfo | undefined>(() => roles.value.find((item) => item.key === selectedKey.value))
const readonly = computed(() => selectedKey.value === 'admin')

function errorOf(err: unknown): string {
  if (err instanceof ApiError) return err.message
  const payload = (err as { response?: { data?: { message?: string } } })?.response?.data
  return payload?.message || ''
}

function warn(err: unknown) {
  const message = errorOf(err)
  ElMessage.warning(message && message !== 'Network Error' ? message : '数据服务暂不可用')
}

async function loadRoles() {
  const list = await api.get<RoleInfo[]>('/roles')
  roles.value = (list || []).map((item) => ({ ...item, permissions: item.permissions || [] }))
  if (!roles.value.some((item) => item.key === selectedKey.value)) {
    selectedKey.value = roles.value[0]?.key || ''
  }
  const current = selectedRole.value
  selectedPerms.value = current ? [...(current.permissions || [])] : []
}

async function loadPermissions() {
  const list = await api.get<Array<PermissionItem & { children?: PermissionItem[] }>>('/permissions')
  const flat: PermissionItem[] = []
  const walk = (items: Array<PermissionItem & { children?: PermissionItem[] }>) => {
    for (const item of items || []) {
      flat.push({ key: item.key, name: item.name, module: item.module })
      if (item.children?.length) walk(item.children)
    }
  }
  walk(list || [])
  permissions.value = flat
}

async function reload() {
  loading.value = true
  try {
    await Promise.all([loadRoles(), loadPermissions()])
  } catch (err) {
    warn(err)
  } finally {
    loading.value = false
  }
}

function selectRole(item: RoleInfo) {
  selectedKey.value = item.key
  selectedPerms.value = [...(item.permissions || [])]
}

function moduleAllChecked(group: PermissionGroup): boolean {
  return group.items.length > 0 && group.items.every((item) => selectedPerms.value.includes(item.key))
}

function moduleIndeterminate(group: PermissionGroup): boolean {
  const selected = group.items.filter((item) => selectedPerms.value.includes(item.key)).length
  return selected > 0 && selected < group.items.length
}

function toggleModule(group: PermissionGroup, val: CheckboxValueType) {
  if (readonly.value) return
  const keys = group.items.map((item) => item.key)
  if (val) {
    selectedPerms.value = Array.from(new Set([...selectedPerms.value, ...keys]))
  } else {
    selectedPerms.value = selectedPerms.value.filter((key) => !keys.includes(key))
  }
}

async function save() {
  if (!selectedRole.value || readonly.value) return
  saving.value = true
  try {
    const res = await api.put<{ ok: boolean; permissions: string[] }>(
      `/roles/${selectedRole.value.key}/permissions`,
      { permissions: selectedPerms.value },
    )
    const saved = res?.permissions || selectedPerms.value
    const role = roles.value.find((item) => item.key === selectedKey.value)
    if (role) role.permissions = [...saved]
    selectedPerms.value = [...saved]
    ElMessage.success(`「${selectedRole.value.name}」的权限已保存（${saved.length} 项）`)
  } catch (err) {
    warn(err)
  } finally {
    saving.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.role-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

@media (max-width: 1000px) {
  .role-layout {
    grid-template-columns: 1fr;
  }
}

.role-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-bottom: 12px;
}

.role-item {
  border: 1px solid var(--ap-border);
  border-radius: var(--ap-radius);
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
  position: relative;
}

.role-item:hover {
  border-color: #b9cff5;
  box-shadow: 0 4px 12px rgba(31, 95, 214, 0.08);
}

.role-item.active {
  border-color: var(--ap-primary);
  background: #f5f8ff;
  box-shadow: 0 4px 14px rgba(31, 95, 214, 0.12);
}

.role-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.role-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, #e8f0ff, #d6e4ff);
  color: var(--ap-primary);
  flex-shrink: 0;
}

.role-name {
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
}

.role-key {
  font-size: 12px;
  color: #8b9aae;
  margin-top: 2px;
}

.role-arrow {
  color: #a9b7c9;
  font-size: 13px;
}

.role-desc {
  margin-top: 9px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--ap-text-secondary);
}

.role-stats {
  margin-top: 9px;
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #7b8ba1;
}

.role-stats span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.role-loading {
  height: 2px;
}

.perm-panel {
  padding-bottom: 16px;
}

.perm-modules {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.perm-module {
  border: 1px solid var(--ap-border);
  border-radius: var(--ap-radius);
  padding: 10px 14px 6px;
}

.perm-module-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--ap-border);
}

.perm-module-name {
  font-size: 13px;
  font-weight: 600;
  color: #40536b;
}

.perm-items {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 2px 12px;
  padding-top: 6px;
}

.perm-name {
  font-size: 13px;
}

.perm-key {
  margin-left: 6px;
  font-size: 11px;
  color: #9aa8bb;
}

.perm-footer {
  margin-top: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid var(--ap-border);
  padding-top: 14px;
}
</style>
