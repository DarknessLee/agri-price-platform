<template>
  <div class="page-header">
    <div class="left">
      <h2>{{ title }}</h2>
      <p v-if="subtitle">{{ subtitle }}</p>
    </div>
    <div class="right">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.left h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 600;
  color: #1c2a3a;
}

.left p {
  margin: 6px 0 0;
  font-size: 13px;
  color: #7b8ba1;
}

.right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
</style>
