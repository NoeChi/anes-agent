<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errMsg } from '@/api/client'
import type { Category, RuleSpec, ToolInfo } from '@/api/types'
import { useWs } from '@/api/ws'
import RuleBuilderModal from '@/components/RuleBuilderModal.vue'
import ToolCard from '@/components/ToolCard.vue'
import TrainModelModal from '@/components/TrainModelModal.vue'
import UploadModelModal from '@/components/UploadModelModal.vue'
import { toast } from '@/composables/useToast'
import { CATEGORY } from '@/utils/format'

const tools = ref<ToolInfo[]>([])
const filter = ref<'all' | Category>('all')
// undefined＝關閉，null＝新增，RuleSpec＝編輯
const ruleSpec = ref<RuleSpec | null | undefined>(undefined)
const showTrain = ref(false)
const showUpload = ref(false)

async function load() {
  try {
    tools.value = await api.get<ToolInfo[]>('/api/tools')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

onMounted(load)
useWs('tools_changed', () => void load())

const counts = computed(() => {
  const c: Record<string, number> = { all: tools.value.length }
  for (const t of tools.value) c[t.category] = (c[t.category] ?? 0) + 1
  return c
})

const categories = computed(() => {
  const cats = (Object.keys(CATEGORY) as Category[]).filter((c) => counts.value[c])
  return [{ id: 'all' as const, label: '全部' }, ...cats.map((c) => ({ id: c, label: CATEGORY[c].label }))]
})

const visible = computed(() => tools.value.filter((t) => filter.value === 'all' || t.category === filter.value))

async function reload() {
  try {
    const r = await api.post<{ count: number }>('/api/tools/reload', {})
    toast(`已重新載入，共 ${r.count} 個工具`, 'ok')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}
</script>

<template>
  <section class="page active">
    <div class="page-head">
      <div>
        <h1>工具庫</h1>
        <p class="muted">「工具」是 AI 查房時判斷病人狀況的方法：規則、臨床評分、機器學習或深度學習模型。啟用中的工具會在每次查房時對每位病人執行，AI 助理也能在對話中呼叫。</p>
      </div>
      <div class="row">
        <button class="btn btn-primary" @click="ruleSpec = null">＋ 新增規則（免寫程式）</button>
        <button class="btn btn-primary" @click="showTrain = true">🧠 訓練 AI 模型（免寫程式）</button>
        <button class="btn" @click="showUpload = true">⬆ 上傳模型檔</button>
        <button class="btn btn-ghost" title="重新讀取外掛、規則與模型" @click="reload">↻ 重新載入</button>
      </div>
    </div>
    <div class="toolbar">
      <div class="chips">
        <button v-for="c in categories" :key="c.id" class="chip" :class="{ active: filter === c.id }" @click="filter = c.id">
          {{ c.label }}<span class="count">{{ counts[c.id] }}</span>
        </button>
      </div>
    </div>
    <div class="tgrid">
      <ToolCard v-for="t in visible" :key="t.id" :tool="t" @edit="ruleSpec = $event" @changed="load" />
      <div v-if="!visible.length" class="empty">沒有工具</div>
    </div>
    <RuleBuilderModal v-if="ruleSpec !== undefined" :spec="ruleSpec" @close="ruleSpec = undefined" @saved="load" />
    <TrainModelModal v-if="showTrain" @close="showTrain = false" @trained="load" />
    <UploadModelModal v-if="showUpload" @close="showUpload = false" @uploaded="load" />
  </section>
</template>
