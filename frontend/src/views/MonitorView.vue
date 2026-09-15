<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { PatientBrief } from '@/api/types'
import PatientCard from '@/components/PatientCard.vue'
import { openPatient } from '@/composables/usePatientModal'
import { useChatStore } from '@/stores/chat'
import { useLiveStore } from '@/stores/live'
import { fmtTime } from '@/utils/format'

type Filter = 'all' | 'OR' | 'PACU' | 'critical' | 'warning'

const live = useLiveStore()
const chat = useChatStore()
const router = useRouter()
const filter = ref<Filter>('all')
const search = ref('')
const sort = ref<'bed' | 'sev'>('bed')

const FILTERS: { id: Filter; label: string; cls: string }[] = [
  { id: 'all', label: '全部', cls: '' },
  { id: 'OR', label: '手術室', cls: '' },
  { id: 'PACU', label: '恢復室', cls: '' },
  { id: 'critical', label: '🔴 危急', cls: 'chip-crit' },
  { id: 'warning', label: '🟠 警示', cls: 'chip-warn' },
]
const ORDER: Record<string, number> = { critical: 0, warning: 1, info: 2, normal: 3, unchecked: 4 }

function visible(p: PatientBrief): boolean {
  const f = filter.value
  if ((f === 'OR' || f === 'PACU') && p.location !== f) return false
  if ((f === 'critical' || f === 'warning') && p.status !== f) return false
  const q = search.value.trim().toLowerCase()
  if (q && !`${p.bed} ${p.pid} ${p.surgery} ${p.name}`.toLowerCase().includes(q)) return false
  return true
}

const list = computed(() => {
  const ps = live.patients.filter(visible)
  if (sort.value !== 'sev') return ps
  return [...ps].sort((a, b) => (ORDER[a.status] ?? 5) - (ORDER[b.status] ?? 5) || a.bed.localeCompare(b.bed))
})

const stats = computed(() => {
  const ps = live.patients
  return {
    total: ps.length,
    or: ps.filter((p) => p.location === 'OR').length,
    pacu: ps.filter((p) => p.location === 'PACU').length,
    crit: ps.filter((p) => p.status === 'critical').length,
    warn: ps.filter((p) => p.status === 'warning').length,
  }
})
</script>

<template>
  <section class="page active">
    <div class="page-head">
      <div>
        <h1>即時監控</h1>
        <p class="muted">手術室與恢復室病人的即時生命徵象。點選病人卡片可看詳細資料、趨勢圖、工具判讀並模擬處置。</p>
      </div>
    </div>
    <div class="summary-strip">
      <div class="kpi">
        <div class="kpi-label">病人總數</div>
        <div class="kpi-value">{{ stats.total }}</div>
        <div class="kpi-sub">手術室 {{ stats.or }}／恢復室 {{ stats.pacu }}</div>
      </div>
      <div class="kpi clickable" @click="filter = 'critical'">
        <div class="kpi-label">🔴 危急病人</div>
        <div class="kpi-value crit">{{ stats.crit }}</div>
        <div class="kpi-sub">依最近查房結果</div>
      </div>
      <div class="kpi clickable" @click="filter = 'warning'">
        <div class="kpi-label">🟠 警示病人</div>
        <div class="kpi-value warn">{{ stats.warn }}</div>
        <div class="kpi-sub">依最近查房結果</div>
      </div>
      <div class="kpi clickable" @click="router.push('/rounds')">
        <div class="kpi-label">進行中警示</div>
        <div class="kpi-value">{{ live.activeAlerts }}</div>
        <div class="kpi-sub">點選查看</div>
      </div>
      <div class="kpi clickable" @click="chat.openPanel()">
        <div class="kpi-label">AI 待確認處置</div>
        <div class="kpi-value">{{ live.pendingActions }}</div>
        <div class="kpi-sub">需要您確認</div>
      </div>
      <div class="kpi clickable" @click="router.push('/rounds')">
        <div class="kpi-label">上次查房</div>
        <div class="kpi-value">{{ live.schedule?.last_round ? fmtTime(live.schedule.last_round) : '—' }}</div>
        <div class="kpi-sub">下一次 {{ live.schedule?.next_due ? fmtTime(live.schedule.next_due) : '未排程' }}</div>
      </div>
    </div>
    <div class="toolbar">
      <div class="chips">
        <button v-for="f in FILTERS" :key="f.id" class="chip" :class="[f.cls, { active: filter === f.id }]" @click="filter = f.id">{{ f.label }}</button>
      </div>
      <input v-model="search" class="input search" placeholder="搜尋床位、病號或手術…" />
      <select v-model="sort" class="input">
        <option value="bed">依床位排序</option>
        <option value="sev">依嚴重度排序</option>
      </select>
      <span class="legend muted">卡片左側顏色＝最近一次查房結果；紅／橘色數字＝超出常見範圍</span>
    </div>
    <div class="pgrid">
      <PatientCard v-for="p in list" :key="p.pid" :patient="p" @click="openPatient(p.pid)" />
      <div v-if="!list.length" class="empty">沒有符合條件的病人</div>
    </div>
    <div class="card log-card">
      <div class="card-title">病人動態（轉入恢復室、新病人、情境演練）</div>
      <ul class="log">
        <li v-for="e in live.logs" :key="`${e.t}|${e.text}`" :class="e.level"><span class="t">{{ fmtTime(e.t) }}</span>{{ e.text }}</li>
      </ul>
    </div>
  </section>
</template>
