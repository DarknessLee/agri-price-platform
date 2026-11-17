<template>
  <div class="stat-card" :class="`stat-${tone}`">
    <div class="stat-head">
      <span class="stat-label">{{ label }}</span>
      <span class="stat-dot" aria-hidden="true" />
    </div>
    <div class="stat-value">
      {{ value }}<small v-if="unit">{{ unit }}</small>
    </div>
    <div class="stat-hint" :class="hintClass">{{ hint || ' ' }}</div>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string;
    value: string | number;
    unit?: string;
    hint?: string;
    hintClass?: string;
    tone?: 'blue' | 'green' | 'orange' | 'red';
  }>(),
  { unit: '', hint: '', hintClass: '', tone: 'blue' },
);
</script>

<style scoped>
.stat-card {
  position: relative;
  padding: 11px 12px 10px;
  overflow: hidden;
  border-radius: 12px;
  background: var(--ap-card);
  box-shadow: 0 1px 3px rgba(18, 35, 63, 0.06);
}

.stat-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 3px;
  background: var(--tone, var(--ap-primary));
}

.stat-blue {
  --tone: #1f5fd6;
}

.stat-green {
  --tone: #1f9d63;
}

.stat-orange {
  --tone: #e08b1f;
}

.stat-red {
  --tone: #d64545;
}

.stat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.stat-label {
  font-size: 12px;
  color: var(--ap-muted);
}

.stat-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--tone, var(--ap-primary));
  opacity: 0.55;
}

.stat-value {
  margin-top: 5px;
  overflow: hidden;
  font-size: 21px;
  font-weight: 600;
  line-height: 1.25;
  color: var(--ap-text);
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-value small {
  margin-left: 3px;
  font-size: 11px;
  font-weight: 400;
  color: var(--ap-muted);
}

.stat-hint {
  margin-top: 3px;
  overflow: hidden;
  font-size: 11px;
  color: var(--ap-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
