<template>
  <div class="kpi-card" :class="{ clickable }" @click="clickable && $emit('click')">
    <div class="kpi-icon" :style="{ background: iconBg }">
      <el-icon :size="20"><component :is="icon || 'DataLine'" /></el-icon>
    </div>
    <div class="kpi-body">
      <div class="kpi-label">{{ label }}</div>
      <div class="kpi-value">
        <span class="value">{{ value }}</span>
        <span v-if="unit" class="unit">{{ unit }}</span>
      </div>
      <div v-if="hint" class="kpi-hint">
        <slot name="hint">{{ hint }}</slot>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    label: string
    value: string | number
    unit?: string
    hint?: string
    icon?: string
    tone?: 'blue' | 'green' | 'orange' | 'red' | 'purple'
    clickable?: boolean
  }>(),
  { tone: 'blue', clickable: false },
)
defineEmits<{ (e: 'click'): void }>()

const iconBg = computed(() => {
  const map: Record<string, string> = {
    blue: 'linear-gradient(135deg, #e8f0ff, #d6e4ff); color: #1f5fd6',
    green: 'linear-gradient(135deg, #e6f7ef, #d3f0e2); color: #1c9c6b',
    orange: 'linear-gradient(135deg, #fff2e4, #ffe4c7); color: #d9822b',
    red: 'linear-gradient(135deg, #ffeaea, #ffd9d9); color: #d64545',
    purple: 'linear-gradient(135deg, #f1ebff, #e4d9ff); color: #6f42c1',
  }
  return map[props.tone] || map.blue
})
</script>

<style scoped>
.kpi-card {
  display: flex;
  gap: 14px;
  padding: 16px 18px;
  background: #fff;
  border-radius: var(--ap-radius);
  box-shadow: var(--ap-card-shadow);
}

.kpi-card.clickable {
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.kpi-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(20, 40, 80, 0.12);
}

.kpi-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 10px;
  flex-shrink: 0;
}

.kpi-body {
  min-width: 0;
}

.kpi-label {
  font-size: 13px;
  color: #7b8ba1;
}

.kpi-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-top: 4px;
}

.kpi-value .value {
  font-size: 24px;
  font-weight: 600;
  color: #16233a;
  font-variant-numeric: tabular-nums;
}

.kpi-value .unit {
  font-size: 12px;
  color: #8b9aae;
}

.kpi-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #8b9aae;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
