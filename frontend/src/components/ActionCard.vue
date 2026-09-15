<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, errMsg } from '@/api/client'
import type { PendingAction } from '@/api/types'
import { openPatient } from '@/composables/usePatientModal'
import { toast } from '@/composables/useToast'

const props = defineProps<{ action: PendingAction }>()
const emit = defineEmits<{ resolved: [action: PendingAction] }>()
const busy = ref(false)

const statusCls = computed(() => ({ pending: '', confirmed: 'confirmed', rejected: 'rejected', failed: 'failed' })[props.action.status])
const doneText = computed(() => ({ pending: '', confirmed: '✅ 已執行', rejected: '❌ 未採納', failed: '⚠️ 執行失敗' })[props.action.status])

async function resolve(confirm: boolean) {
  busy.value = true
  try {
    const a = await api.post<PendingAction>(`/api/actions/${props.action.id}`, { confirm })
    toast(a.status === 'confirmed' ? (a.result ?? '已執行') : '已記錄：不採納此建議', a.status === 'confirmed' ? 'ok' : 'info')
    emit('resolved', a)
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="action-card" :class="statusCls">
    <div class="ac-title">🤖 AI 建議處置｜{{ action.bed }}（{{ action.pid }}）</div>
    <div><b>{{ action.label }}</b></div>
    <div class="muted">理由：{{ action.reason }}</div>
    <div v-if="action.status === 'pending'" class="row" style="margin-top: 6px">
      <button class="btn btn-sm btn-primary" :disabled="busy" @click="resolve(true)">✓ 確認執行</button>
      <button class="btn btn-sm" :disabled="busy" @click="resolve(false)">不採納</button>
      <button class="btn btn-sm btn-ghost" @click="openPatient(action.pid)">查看病人</button>
    </div>
    <div v-else style="margin-top: 4px">{{ doneText }}{{ action.result ? '：' + action.result : '' }}</div>
  </div>
</template>
