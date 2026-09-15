<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { connectWs, useWs, wsState } from '@/api/ws'
import ChatPanel from '@/components/ChatPanel.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import PatientDetailModal from '@/components/PatientDetailModal.vue'
import SideNav from '@/components/SideNav.vue'
import ToastHost from '@/components/ToastHost.vue'
import TopBar from '@/components/TopBar.vue'
import { closePatient, openPatient, openPatientId } from '@/composables/usePatientModal'
import { toast } from '@/composables/useToast'
import { useChatStore } from '@/stores/chat'
import { useLiveStore } from '@/stores/live'

const live = useLiveStore()
const chat = useChatStore()
const route = useRoute()
const router = useRouter()
const mainEl = ref<HTMLElement | null>(null)

onMounted(async () => {
  connectWs()
  void chat.init()
  try {
    await Promise.all([live.refreshState(), live.loadPatients()])
  } catch {
    /* 連線後由 WebSocket 補上 */
  }
})

useWs('hello', (d) => {
  live.settings = d.settings
  live.llm = d.llm
  live.ml = d.ml
})
useWs('tick', (d) => live.applyTick(d))
useWs('settings_changed', (s) => live.applySettings(s))
useWs('ml_status', (m) => {
  live.ml = m
})
useWs('sim_reset', () => live.clearLogs())
useWs('round_completed', (d) => {
  if (d.trigger === 'recheck') return
  toast(`${d.trigger_label}完成：危急 ${d.n_critical} 位、警示 ${d.n_warning} 位、新問題 ${d.new_alerts} 項`, d.n_critical ? 'warn' : 'ok', {
    action: { label: '查看報告', onClick: () => void router.push('/rounds') },
  })
})
useWs('round_summary', (d) => {
  if (d.summary_error) toast(`AI 查房摘要失敗：${d.summary_error}`, 'error')
  else if (d.summary_source === 'ai' && route.path !== '/rounds') {
    toast(`🤖 AI 已完成 ${d.id} 查房摘要`, 'info', { action: { label: '閱讀', onClick: () => void router.push('/rounds') } })
  }
})
useWs('alert', (a) => {
  if (a.severity === 'critical' && !a.acknowledged) {
    toast(`🔴 ${a.bed}（${a.pid}）${a.title}`, 'crit', { action: { label: '查看病人', onClick: () => openPatient(a.pid) } })
  }
})
useWs('pending_action', (a) => {
  if (a.session_id === chat.sessionId) chat.addAction(a)
  toast(`🤖 AI 建議對 ${a.bed}（${a.pid}）執行「${a.label}」，需要你確認`, 'warn', {
    action: { label: '前往確認', onClick: () => chat.openPanel() },
    timeout: 10000,
  })
})
useWs('action_resolved', (a) => chat.updateAction(a))
useWs('chat_step', (ev) => chat.onStep(ev))

watch(() => chat.open, (open) => document.body.classList.toggle('chat-open', open))
watch(() => route.path, () => {
  if (mainEl.value) mainEl.value.scrollTop = 0
})
</script>

<template>
  <div v-if="wsState.attempted && !wsState.connected" class="conn-banner">與系統的連線中斷，正在重新連線…</div>
  <TopBar />
  <div class="layout">
    <SideNav />
    <main ref="mainEl" class="main">
      <RouterView />
    </main>
    <ChatPanel />
  </div>
  <PatientDetailModal v-if="openPatientId" :key="openPatientId" :pid="openPatientId" @close="closePatient" />
  <ConfirmDialog />
  <ToastHost />
</template>
