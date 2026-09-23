<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import ActionCard from '@/components/ActionCard.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import type { PendingAction } from '@/api/types'
import { useChatStore } from '@/stores/chat'
import { useLiveStore } from '@/stores/live'

const chat = useChatStore()
const live = useLiveStore()
const text = ref('')
const bodyEl = ref<HTMLElement | null>(null)
const inputEl = ref<HTMLTextAreaElement | null>(null)

const SUGGESTIONS = ['目前有哪些危急病人？', '幫我總結最近一次查房', '把自動查房改成每 5 分鐘', '有哪些 AI 模型工具？', '建立規則：糖尿病病人血糖超過 250 列為危急']
const WELCOME = '👋 我是**麻醉 AI 查房助理**。\n\n我會依照你設定的時間自動查房，也可以隨時幫你：\n- 查看病人狀況與趨勢、解讀工具與 AI 模型結果\n- 立即查房、整理警示與查房摘要\n- 修改查房頻率、調整工具門檻、建立規則與技能\n- 提出處置建議（需要你確認才會執行）\n\n點下方的建議問題開始吧！'

const available = computed(() => !!live.llm?.available)

function send(value?: string) {
  const content = value ?? text.value
  if (!content.trim() || chat.busy) return
  if (value === undefined) text.value = ''
  void chat.send(content)
}

function onKeydown(e: KeyboardEvent) {
  // 中文輸入法選字時按 Enter 不送出
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
    e.preventDefault()
    send()
  }
}

function onResolved(a: PendingAction) {
  chat.updateAction(a)
}

function scrollToBottom() {
  void nextTick(() => {
    if (bodyEl.value) bodyEl.value.scrollTop = bodyEl.value.scrollHeight
  })
}

watch(() => chat.items, scrollToBottom, { deep: true })
watch(() => chat.open, (open) => {
  if (open) setTimeout(() => inputEl.value?.focus(), 50)
})
</script>

<template>
  <aside class="chat">
    <div class="chat-head">
      <div class="row">
        <b>💬 AI 助理</b>
        <span v-if="available" class="pill pill-ok" :title="live.llm?.model ?? ''">{{ live.llm?.provider_label ?? 'AI' }}</span>
        <span v-else class="pill pill-off" title="到「設定」輸入 AI 供應商的 API 金鑰即可開啟完整 AI 對話">離線模式</span>
      </div>
      <div class="row">
        <button class="btn btn-sm btn-ghost" title="清除對話，重新開始" @click="chat.reset()">新對話</button>
        <button class="btn btn-sm btn-ghost chat-close" @click="chat.open = false">✕</button>
      </div>
    </div>
    <div ref="bodyEl" class="chat-body">
      <template v-for="item in chat.items" :key="item.key">
        <div v-if="item.kind === 'welcome'" class="msg msg-ai"><MarkdownView :source="WELCOME" /></div>
        <div v-else-if="item.kind === 'user'" class="msg msg-user">{{ item.text }}</div>
        <div v-else-if="item.kind === 'pending'" class="msg msg-ai">
          <div class="msg-steps">
            <div v-for="(s, i) in item.steps" :key="s.id ?? i" class="s" :class="s.status">{{ s.label }}</div>
          </div>
          <span class="thinking"><i /><i /><i /> {{ available ? 'AI 思考中' : '處理中' }}</span>
        </div>
        <div v-else-if="item.kind === 'ai'" class="msg msg-ai" :class="{ error: !!item.error }">
          <details v-if="item.steps?.length">
            <summary class="faint" style="font-weight: 400">🔧 使用了 {{ item.steps.length }} 個工具</summary>
            <div class="msg-steps">
              <div v-for="(s, i) in item.steps" :key="s.id ?? i" class="s" :class="s.status || 'done'">{{ s.label }}</div>
            </div>
          </details>
          <MarkdownView :source="item.text" />
        </div>
        <ActionCard v-else-if="item.kind === 'action' && item.action" :action="item.action" @resolved="onResolved" />
      </template>
    </div>
    <div v-if="chat.showSuggestions" class="chat-suggest">
      <button v-for="s in SUGGESTIONS" :key="s" @click="send(s)">{{ s }}</button>
    </div>
    <form class="chat-input" @submit.prevent="send()">
      <textarea
        ref="inputEl"
        v-model="text"
        rows="2"
        placeholder="輸入問題，例如：OR-05 的病人怎麼了？（Enter 送出，Shift+Enter 換行）"
        @keydown="onKeydown"
      />
      <button class="btn btn-primary" type="submit" :disabled="chat.busy">送出</button>
    </form>
  </aside>
</template>
