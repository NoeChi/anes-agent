<script setup lang="ts">
import { computed } from 'vue'
import { md } from '@/utils/markdown'

const props = defineProps<{ source: string | null | undefined; empty?: string }>()
// md() 會先跳脫所有 HTML，只輸出自己產生的安全標籤
const html = computed(() => md(props.source))
</script>

<template>
  <div v-if="html" class="md" v-html="html" />
  <div v-else-if="empty" class="md"><span class="muted">{{ empty }}</span></div>
</template>
