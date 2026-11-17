<template>
  <div class="h5-chart" :style="{ height: `${height}px` }">
    <div ref="el" class="h5-chart-canvas" />
    <div v-if="empty" class="h5-chart-empty">{{ emptyText }}</div>
  </div>
</template>

<script setup lang="ts">
import * as echarts from 'echarts';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    option: Record<string, unknown>;
    height?: number;
    empty?: boolean;
    emptyText?: string;
  }>(),
  { height: 200, empty: false, emptyText: '暂无数据' },
);

const el = ref<HTMLDivElement | null>(null);
let chart: echarts.ECharts | null = null;
let observer: ResizeObserver | null = null;

function render(): void {
  if (!el.value) return;
  if (!chart) {
    chart = echarts.init(el.value, undefined, { renderer: 'canvas' });
  }
  chart.setOption({ ...(props.option as echarts.EChartsOption), animationDuration: 400 }, true);
  chart.resize();
}

onMounted(() => {
  render();
  if (el.value && typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => chart?.resize());
    observer.observe(el.value);
  }
});

watch(
  () => props.option,
  () => render(),
  { deep: true },
);

onBeforeUnmount(() => {
  observer?.disconnect();
  chart?.dispose();
  chart = null;
});

defineExpose({ getInstance: () => chart, resize: () => chart?.resize() });
</script>

<style scoped>
.h5-chart {
  position: relative;
  width: 100%;
}

.h5-chart-canvas {
  width: 100%;
  height: 100%;
}

.h5-chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--ap-muted);
  background: rgba(255, 255, 255, 0.85);
}
</style>
