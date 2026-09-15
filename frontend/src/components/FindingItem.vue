<script setup lang="ts">
import { computed } from 'vue'
import type { Finding } from '@/api/types'
import { sevOf } from '@/utils/format'

const props = defineProps<{ finding: Finding }>()
const sev = computed(() => sevOf(props.finding.severity))
</script>

<template>
  <div class="finding" :class="finding.severity">
    <div class="finding-title">
      <span class="badge" :class="sev.badge">{{ sev.label }}</span>{{ finding.title }}
      <span v-if="finding.new" class="badge badge-crit">🆕 新</span>
    </div>
    <div class="finding-detail">{{ finding.detail }}</div>
    <div v-if="finding.suggestion" class="finding-sug">💡 {{ finding.suggestion }}</div>
    <div v-if="finding.tool_name" class="finding-tool">來源工具：{{ finding.tool_name }}</div>
  </div>
</template>
