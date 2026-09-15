<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { drawChart, type ChartOptions, type ChartSeries } from '@/utils/chart'

const props = defineProps<{ ts: number[]; series: ChartSeries[]; options?: ChartOptions }>()
const canvas = ref<HTMLCanvasElement | null>(null)
let observer: ResizeObserver | null = null

function draw() {
  if (canvas.value) drawChart(canvas.value, props.ts, props.series, props.options ?? {})
}

onMounted(() => {
  draw()
  if (canvas.value) {
    observer = new ResizeObserver(() => draw())
    observer.observe(canvas.value)
  }
})
onUnmounted(() => observer?.disconnect())
watch(() => [props.ts, props.series, props.options], draw)
</script>

<template>
  <canvas ref="canvas" />
</template>
