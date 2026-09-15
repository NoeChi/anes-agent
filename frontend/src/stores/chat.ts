/* AI 助理對話狀態 */
import { defineStore } from 'pinia'
import { api, errMsg } from '@/api/client'
import type { ChatDisplayMessage, ChatResponse, ChatStep, ChatStepEvent, PendingAction } from '@/api/types'

export interface ChatItem {
  key: string
  kind: 'welcome' | 'user' | 'ai' | 'pending' | 'action'
  text?: string
  steps?: ChatStep[]
  error?: string | null
  action?: PendingAction
}

const SID_KEY = 'anes-chat-sid'
let keySeq = 0
const nextKey = () => `c${++keySeq}`

function newSid(): string {
  const sid = Math.random().toString(36).slice(2, 14)
  try {
    localStorage.setItem(SID_KEY, sid)
  } catch {
    /* 無法儲存時，每次重新開始 */
  }
  return sid
}

function loadSid(): string {
  try {
    const sid = localStorage.getItem(SID_KEY)
    if (sid) return sid
  } catch {
    /* 忽略 */
  }
  return newSid()
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    sessionId: '',
    items: [] as ChatItem[],
    busy: false,
    open: false,
    showSuggestions: true,
    initialized: false,
  }),
  actions: {
    async init() {
      if (this.initialized) return
      this.initialized = true
      this.sessionId = loadSid()
      await this.loadHistory()
    },
    async loadHistory() {
      let messages: ChatDisplayMessage[] = []
      try {
        messages = (await api.get<{ messages: ChatDisplayMessage[] }>(`/api/chat/${this.sessionId}`)).messages
      } catch {
        messages = []
      }
      const items: ChatItem[] = []
      if (!messages.length) {
        items.push({ key: nextKey(), kind: 'welcome' })
        this.showSuggestions = true
      } else {
        this.showSuggestions = false
        for (const m of messages) {
          items.push(m.role === 'user'
            ? { key: nextKey(), kind: 'user', text: m.text }
            : { key: nextKey(), kind: 'ai', text: m.text, steps: m.steps ?? [], error: m.error ?? null })
        }
      }
      this.items = items
      try {
        const actions = await api.get<PendingAction[]>('/api/actions')
        actions.filter((a) => a.session_id === this.sessionId).reverse().forEach((a) => this.addAction(a))
      } catch {
        /* 忽略 */
      }
    },
    addAction(a: PendingAction) {
      if (this.items.some((i) => i.kind === 'action' && i.action?.id === a.id)) return
      this.items.push({ key: nextKey(), kind: 'action', action: a })
    },
    updateAction(a: PendingAction) {
      const item = this.items.find((i) => i.kind === 'action' && i.action?.id === a.id)
      if (item) item.action = a
    },
    async send(raw: string) {
      const text = raw.trim()
      if (!text || this.busy) return
      this.busy = true
      this.showSuggestions = false
      this.items.push({ key: nextKey(), kind: 'user', text })
      const pendingKey = nextKey()
      this.items.push({ key: pendingKey, kind: 'pending', steps: [] })
      try {
        const res = await api.post<ChatResponse>('/api/chat', { session_id: this.sessionId, message: text })
        this.items = this.items.filter((i) => i.key !== pendingKey)
        this.items.push({ key: nextKey(), kind: 'ai', text: res.reply, steps: res.steps ?? [], error: res.error ?? null })
      } catch (e) {
        this.items = this.items.filter((i) => i.key !== pendingKey)
        this.items.push({ key: nextKey(), kind: 'ai', text: `⚠️ ${errMsg(e)}`, steps: [], error: errMsg(e) })
      } finally {
        this.busy = false
      }
    },
    onStep(ev: ChatStepEvent) {
      if (!this.busy || ev.session_id !== this.sessionId) return
      const pending = this.items.find((i) => i.kind === 'pending')
      if (!pending) return
      if (!pending.steps) pending.steps = []
      const existing = pending.steps.find((s) => s.id === ev.id)
      if (existing) {
        existing.status = ev.status
        existing.label = ev.label
      } else {
        pending.steps.push({ id: ev.id, tool: ev.tool, label: ev.label, status: ev.status })
      }
    },
    async reset() {
      if (this.busy) return
      try {
        await api.del(`/api/chat/${this.sessionId}`)
      } catch {
        /* 忽略 */
      }
      this.sessionId = newSid()
      this.items = [{ key: nextKey(), kind: 'welcome' }]
      this.showSuggestions = true
    },
    openPanel() {
      this.open = true
    },
    ask(text: string) {
      this.open = true
      void this.send(text)
    },
  },
})
