<template>
  <div class="base-chart" :style="{ height: typeof height === 'number' ? `${height}px` : height }">
    <div ref="containerRef" class="chart-container" />
    <div v-if="empty" class="chart-empty">
      <el-empty :description="emptyText" :image-size="72" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = withDefaults(
  defineProps<{
    option: echarts.EChartsOption
    height?: number | string
    loading?: boolean
    empty?: boolean
    emptyText?: string
  }>(),
  {
    height: 320,
    loading: false,
    empty: false,
    emptyText: '暂无数据',
  },
)

const containerRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

function render() {
  if (!containerRef.value) return
  if (!chart) {
    chart = echarts.init(containerRef.value, undefined, { renderer: 'canvas' })
  }
  chart.setOption(props.option || {}, true)
  if (props.loading) chart.showLoading('default', { text: '加载中', color: '#1f5fd6' })
  else chart.hideLoading()
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  render()
  observer = new ResizeObserver(() => resize())
  if (containerRef.value) observer.observe(containerRef.value)
  window.addEventListener('resize', resize)
})

watch(
  () => props.option,
  () => render(),
  { deep: true },
)

watch(
  () => props.loading,
  () => render(),
)

onBeforeUnmount(() => {
  observer?.disconnect()
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})

defineExpose({ resize, getInstance: () => chart })
</script>

<style scoped>
.base-chart {
  position: relative;
  width: 100%;
}

.chart-container {
  width: 100%;
  height: 100%;
}

.chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.86);
}
</style>
