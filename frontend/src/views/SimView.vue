<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, errMsg } from '@/api/client'
import type { SimEventsResponse, SimulationSettings } from '@/api/types'
import { confirmDialog } from '@/composables/useDialog'
import { openPatient } from '@/composables/usePatientModal'
import { toast } from '@/composables/useToast'
import { useLiveStore } from '@/stores/live'
import { locationLabel } from '@/utils/format'

const live = useLiveStore()
const events = ref<SimEventsResponse | null>(null)
const speed = ref(5)
const rate = ref(1)
const pid = ref('')
const eventType = ref('')
let timer: number | undefined
let sendTimer: number | undefined
let editing = false

const sim = computed(() => live.settings?.simulation)

watch(sim, (s) => {
  if (!s || editing) return
  speed.value = s.speed
  rate.value = s.event_rate
}, { immediate: true, deep: true })

watch(() => live.patients.length, () => {
  if (!pid.value && live.patients[0]) pid.value = live.patients[0].pid
}, { immediate: true })

const selectedEvent = computed(() => events.value?.catalog.find((c) => c.id === eventType.value))

async function control(body: Partial<SimulationSettings>) {
  try {
    const cfg = await api.post<SimulationSettings>('/api/sim/control', body)
    if (live.settings) live.settings.simulation = cfg
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    editing = false
  }
}

function debounceControl(body: Partial<SimulationSettings>) {
  editing = true
  clearTimeout(sendTimer)
  sendTimer = window.setTimeout(() => void control(body), 300)
}

async function refresh() {
  try {
    events.value = await api.get<SimEventsResponse>('/api/sim/events')
    if (!eventType.value && events.value.catalog[0]) eventType.value = events.value.catalog[0].id
  } catch {
    /* 下次再試 */
  }
}

async function reset() {
  if (!(await confirmDialog('重置模擬', '會重新產生 50 位病人，並清除所有查房紀錄與警示（規則、技能與模型不受影響）。確定嗎？', '重置', true))) return
  try {
    await api.post('/api/sim/reset', {})
    toast('模擬已重置', 'ok')
    await refresh()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function inject() {
  try {
    const r = await api.post<{ message: string }>('/api/sim/inject', { pid: pid.value, event: eventType.value })
    toast(r.message, 'ok')
    await refresh()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function demo(event: string) {
  try {
    const r = await api.post<{ message: string; pid: string }>('/api/sim/demo', { event })
    toast(r.message, 'ok', { action: { label: '查看病人', onClick: () => openPatient(r.pid) }, timeout: 8000 })
    await refresh()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

onMounted(() => {
  void refresh()
  timer = window.setInterval(refresh, 3000)
})
onUnmounted(() => {
  clearInterval(timer)
  clearTimeout(sendTimer)
})
</script>

<template>
  <section class="page active">
    <div class="page-head">
      <div>
        <h1>情境演練</h1>
        <p class="muted">控制模擬器、製造臨床事件，用來展示 AI 查房如何及早發現問題、提出建議。</p>
      </div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">🎛️ 模擬控制</div>
        <div class="row" style="margin-bottom: 10px">
          <button class="btn btn-primary" @click="control({ running: !sim?.running })">{{ sim?.running ? '⏸ 暫停模擬' : '▶ 繼續模擬' }}</button>
          <span class="muted">{{ sim?.running ? '模擬進行中' : '模擬已暫停' }}</span>
        </div>
        <div class="field">
          <span>模擬速度 <span class="hint">真實 1 秒＝模擬 {{ speed }} 秒（1 小時的手術約 {{ Math.round(60 / speed) }} 分鐘演完）</span></span>
          <div class="slider-row">
            <input v-model.number="speed" type="range" min="1" max="30" step="1" @input="debounceControl({ speed })" />
            <b>{{ speed }} 倍速</b>
          </div>
        </div>
        <div class="field">
          <span>隨機事件頻率 <span class="hint">0＝不會自然發生新事件（只有你注入的情境）</span></span>
          <div class="slider-row">
            <input v-model.number="rate" type="range" min="0" max="5" step="0.5" @input="debounceControl({ event_rate: rate })" />
            <b>{{ rate }} 倍</b>
          </div>
        </div>
        <button class="btn btn-danger-ghost" @click="reset">↺ 重置模擬（重新產生 50 位病人）</button>
      </div>
      <div class="card">
        <div class="card-title">💉 指定病人注入事件</div>
        <label class="field">
          <span>病人</span>
          <select v-model="pid" class="input">
            <option v-for="p in live.patients" :key="p.pid" :value="p.pid">{{ p.bed }}｜{{ p.pid }}｜{{ p.surgery }}</option>
          </select>
        </label>
        <label class="field">
          <span>事件</span>
          <select v-model="eventType" class="input">
            <option v-for="c in events?.catalog ?? []" :key="c.id" :value="c.id">{{ c.label }}</option>
          </select>
        </label>
        <div v-if="selectedEvent" class="muted" style="margin-bottom: 8px">
          {{ selectedEvent.desc }}<br />有效處置：{{ selectedEvent.treatments.map((t) => t.label).join('、') }}
        </div>
        <button class="btn btn-primary" @click="inject">注入事件</button>
        <div class="card-title" style="margin-top: 16px">📥 匯出模擬資料集</div>
        <div class="row">
          <a class="btn" href="/api/export/vitals.csv?minutes=60">生命徵象 CSV（近 60 分鐘）</a>
          <a class="btn" href="/api/export/vitals.csv?minutes=180">CSV（近 180 分鐘）</a>
          <a class="btn" href="/api/export/patients.json">病人資料 JSON</a>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">🎬 一鍵情境展示 <span class="muted" style="font-weight: 400">系統會自動挑一位適合的病人</span></div>
      <div class="scenario-grid">
        <button v-for="c in events?.catalog ?? []" :key="c.id" class="scenario" @click="demo(c.id)">
          <b>{{ c.label }}</b><small>{{ c.desc }}</small><small>適用：{{ c.locations.map(locationLabel).join('、') }}</small>
        </button>
      </div>
    </div>
    <div class="card">
      <div class="card-title">
        🔍 模擬器內部的真實事件
        <span class="muted" style="font-weight: 400">AI 與工具看不到這張表，只能從生命徵象推斷；可用來檢驗 AI 有沒有抓到</span>
      </div>
      <div class="table-wrap">
        <div v-if="!events?.active.length" class="empty">目前沒有進行中的事件</div>
        <table v-else>
          <thead><tr><th>床位</th><th>事件</th><th>強度</th><th>已發生</th><th>已給予的有效處置</th><th /></tr></thead>
          <tbody>
            <tr v-for="a in events.active" :key="`${a.pid}-${a.type}`">
              <td><b>{{ a.bed }}</b> <span class="faint">{{ a.pid }}</span></td>
              <td>{{ a.label }} <span v-if="a.ending" class="badge badge-ok">緩解中</span></td>
              <td><div class="bar"><div :style="{ width: `${Math.round(a.level * 100)}%` }" /></div></td>
              <td>{{ a.minutes }} 分鐘</td>
              <td class="muted">{{ a.treatments.join('、') || '—' }}</td>
              <td><button class="btn btn-sm" @click="openPatient(a.pid)">查看</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <div class="card-title">🗒️ 建議展示流程（約 5 分鐘）</div>
      <ol>
        <li>到「AI 查房」把查房間隔設為 <b>1 分鐘</b>，AI 摘要選「有異常時才用 AI」。</li>
        <li>在本頁點「惡性高熱」或「急性出血」一鍵情境，記下被選中的床位。</li>
        <li>回到「即時監控」，看該病人的 EtCO₂、心跳、體溫（或血壓、出血量）逐漸變化。</li>
        <li>下一次自動查房時，AI 會標示危急、跳出通知，並套用對應的處置技能撰寫摘要。</li>
        <li>在右側 AI 助理問：「OR-xx 怎麼了？該怎麼處理？」</li>
        <li>AI 提出處置建議卡片，按「確認執行」，回到病人畫面觀察生命徵象恢復。</li>
        <li>最後示範：到「工具庫」新增一條規則，或對 AI 說「幫我建立規則：糖尿病病人血糖超過 250 列為危急」。</li>
      </ol>
    </div>
  </section>
</template>
