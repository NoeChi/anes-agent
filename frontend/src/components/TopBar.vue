<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errMsg } from '@/api/client'
import { useWs } from '@/api/ws'
import { toast } from '@/composables/useToast'
import { useChatStore } from '@/stores/chat'
import { useLiveStore } from '@/stores/live'
import { fmtCountdown, fmtTime } from '@/utils/format'

const live = useLiveStore()
const chat = useChatStore()
const router = useRouter()
const requesting = ref(false)
const roundRunning = ref(false)

useWs('round_started', () => {
  roundRunning.value = true
})
useWs('round_completed', () => {
  roundRunning.value = false
})

const speedText = computed(() => {
  const sim = live.settings?.simulation
  return sim ? `${sim.speed} 倍${sim.running ? '' : '（暫停）'}` : '-'
})

const nextText = computed(() => {
  const s = live.schedule
  if (!s) return '-'
  if (s.busy) return '查房中…'
  return s.next_due ? fmtCountdown(s.seconds_to_next) : '未排程'
})

const aiPill = computed(() => {
  if (live.ml?.state === 'training') return { cls: 'pill pill-warn', text: `🧠 ${live.ml.message || 'AI 模型準備中'}`, title: '' }
  if (live.llm?.available) {
    const provider = live.llm.provider_label ?? 'AI'
    return { cls: 'pill pill-ok', text: `🤖 ${provider} 已連線`, title: live.llm.model ?? '' }
  }
  return { cls: 'pill pill-off', text: '🔌 離線模式', title: '到「設定」輸入 AI 供應商的 API 金鑰即可開啟完整 AI 功能' }
})

async function runRound() {
  requesting.value = true
  try {
    await api.post('/api/rounds/run', { scope: 'all' })
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    requesting.value = false
  }
}
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <span class="logo">🩺</span>
      <div>
        <div class="brand-title">麻醉 AI 查房助理</div>
        <div class="brand-sub">Demo・所有病人皆為模擬資料</div>
      </div>
    </div>
    <div class="top-stats">
      <div class="stat">
        <span class="stat-label">模擬時間</span>
        <span class="stat-value mono">{{ live.simTime ? fmtTime(live.simTime, true) : '--:--:--' }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">模擬速度</span>
        <span class="stat-value">{{ speedText }}</span>
      </div>
      <div class="stat clickable" title="到 AI 查房頁設定" @click="router.push('/rounds')">
        <span class="stat-label">下一次自動查房</span>
        <span class="stat-value mono">{{ nextText }}</span>
      </div>
      <div class="stat clickable" title="查看警示" @click="router.push('/rounds')">
        <span class="stat-label">進行中警示</span>
        <span id="top-alert-count" class="stat-value" :class="{ has: live.activeAlerts > 0 }">{{ live.activeAlerts }}</span>
      </div>
      <span :class="aiPill.cls" :title="aiPill.title">{{ aiPill.text }}</span>
      <button class="btn btn-primary" :class="{ busy: requesting || roundRunning }" @click="runRound">▶ 立即查房</button>
      <button class="btn chat-toggle" @click="chat.open = !chat.open">💬 AI 助理</button>
    </div>
  </header>
</template>
