<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, errMsg } from '@/api/client'
import type { Alert, PendingAction, PublicSettings, RoundBrief, RoundReport, RoundsSettings } from '@/api/types'
import { useWs } from '@/api/ws'
import ActionCard from '@/components/ActionCard.vue'
import FindingItem from '@/components/FindingItem.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import { openPatient } from '@/composables/usePatientModal'
import { toast } from '@/composables/useToast'
import { useLiveStore } from '@/stores/live'
import { fmtCountdown, fmtTime, sevOf } from '@/utils/format'

const live = useLiveStore()

/* ---------- 排程設定 ---------- */
const form = reactive<RoundsSettings>({
  enabled: true,
  mode: 'interval',
  interval_minutes: 2,
  times: [],
  window_enabled: false,
  window_start: '07:00',
  window_end: '22:00',
  scope: 'all',
  ai_summary: 'when_findings',
  critical_recheck_minutes: 1,
})
const dirty = ref(false)
const newTime = ref('')
const runningScope = ref<string | null>(null)
const QUICK = [1, 2, 5, 10, 15, 30, 60]

function fill() {
  const s = live.settings?.rounds
  if (!s) return
  Object.assign(form, { ...s, times: [...s.times] })
  dirty.value = false
}

watch(() => live.settings?.rounds, () => {
  if (!dirty.value) fill()
}, { deep: true, immediate: true })

function markDirty() {
  dirty.value = true
}

function setMode(mode: RoundsSettings['mode']) {
  form.mode = mode
  markDirty()
}

function addTime() {
  if (!newTime.value) {
    toast('請先選擇時間', 'warn')
    return
  }
  if (!form.times.includes(newTime.value)) form.times.push(newTime.value)
  form.times.sort()
  markDirty()
}

function removeTime(t: string) {
  form.times = form.times.filter((x) => x !== t)
  markDirty()
}

async function save() {
  if (form.mode === 'schedule' && !form.times.length) {
    toast('請至少加入一個查房時間點', 'warn')
    return
  }
  try {
    const saved = await api.put<PublicSettings>('/api/settings/rounds', {
      ...form,
      window_start: form.window_start || '07:00',
      window_end: form.window_end || '22:00',
      critical_recheck_minutes: form.critical_recheck_minutes || 0,
    })
    live.settings = saved
    dirty.value = false
    fill()
    toast('查房設定已儲存', 'ok')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function runNow(scope: string) {
  runningScope.value = scope
  try {
    const r = await api.post<RoundBrief>('/api/rounds/run', { scope })
    followLatest.value = true
    toast(`查房完成：危急 ${r.n_critical} 位、警示 ${r.n_warning} 位`, r.n_critical ? 'warn' : 'ok')
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    runningScope.value = null
  }
}

const countdown = computed(() => {
  const s = live.schedule
  if (!s) return '--:--'
  if (s.busy) return '查房中…'
  return s.next_due ? fmtCountdown(s.seconds_to_next) : '未排程'
})

const nextText = computed(() => {
  const s = live.schedule
  if (!s) return ''
  const cfg = live.settings?.rounds
  let text: string
  if (!s.enabled) text = '自動查房已關閉'
  else if (!s.next_due) text = '不在查房時段內'
  else text = `預計 ${fmtTime(s.next_due)} 查房（${cfg?.mode === 'interval' ? `每 ${cfg.interval_minutes} 分鐘` : '每天 ' + (cfg?.times ?? []).join('、')}）`
  if (s.last_round) text += `｜上次查房 ${fmtTime(s.last_round)}`
  return text
})

/* ---------- 查房紀錄 ---------- */
const reports = ref<RoundBrief[]>([])
const selectedId = ref<string | null>(null)
const report = ref<RoundReport | null>(null)
const followLatest = ref(true)

async function loadReports(reselect = true) {
  try {
    reports.value = await api.get<RoundBrief[]>('/api/rounds')
  } catch {
    return
  }
  const list = reports.value
  if (reselect && list.length && (followLatest.value || !selectedId.value)) {
    // 自動顯示最新一次「完整」查房；危急病人複查仍列在清單中可點選
    const target = list.find((r) => r.trigger !== 'recheck') ?? list[0]
    if (target) await selectReport(target.id)
  }
}

async function selectReport(id: string) {
  selectedId.value = id
  try {
    report.value = await api.get<RoundReport>(`/api/rounds/${id}`)
  } catch {
    /* 報告可能已被清除 */
  }
}

function pickReport(id: string) {
  followLatest.value = false
  void selectReport(id)
}

watch(followLatest, (v) => {
  if (v) void loadReports()
})

/* ---------- 警示與處置建議 ---------- */
const alerts = ref<Alert[]>([])
const actions = ref<PendingAction[]>([])

async function loadAlerts() {
  try {
    alerts.value = await api.get<Alert[]>('/api/alerts')
  } catch {
    /* 忽略 */
  }
}

async function ackAlert(id: string) {
  try {
    await api.post(`/api/alerts/${id}/ack`, {})
    await loadAlerts()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function loadActions() {
  try {
    actions.value = await api.get<PendingAction[]>('/api/actions?status=pending')
  } catch {
    /* 忽略 */
  }
}

onMounted(() => {
  fill()
  void loadReports()
  void loadAlerts()
  void loadActions()
})

useWs('round_completed', () => void loadReports())
useWs('round_summary', (d) => {
  if (selectedId.value === d.id) void selectReport(d.id)
  void loadReports(false)
})
useWs('alert', () => void loadAlerts())
useWs('alerts_changed', () => void loadAlerts())
useWs('pending_action', () => void loadActions())
useWs('action_resolved', () => void loadActions())
useWs('sim_reset', () => {
  selectedId.value = null
  report.value = null
  void loadReports()
  void loadAlerts()
})
</script>

<template>
  <section class="page active">
    <div class="page-head">
      <div>
        <h1>AI 查房</h1>
        <p class="muted">設定 AI 多久查房一次。每次查房，AI 會對每位病人執行所有「啟用中」的工具，整理出需要注意的病人並撰寫查房摘要。</p>
      </div>
    </div>
    <div class="grid-2">
      <div class="card" @input="markDirty" @change="markDirty">
        <div class="card-title">
          🗓️ 自動查房排程
          <label class="row" style="font-weight: 500">
            <span>啟用自動查房</span>
            <label class="switch"><input v-model="form.enabled" type="checkbox" /><span /></label>
          </label>
        </div>
        <div class="field">
          <span>查房方式</span>
          <div class="seg">
            <button :class="{ active: form.mode === 'interval' }" @click="setMode('interval')">每隔固定時間</button>
            <button :class="{ active: form.mode === 'schedule' }" @click="setMode('schedule')">每天固定時間點</button>
          </div>
        </div>
        <div v-if="form.mode === 'interval'" class="field">
          <span>每隔幾分鐘查房一次</span>
          <div class="row">
            <input v-model.number="form.interval_minutes" class="input" type="number" min="0.5" max="720" step="0.5" style="width: 120px" />
            <span>分鐘</span>
          </div>
          <div class="quick">
            <button v-for="m in QUICK" :key="m" class="chip" @click="form.interval_minutes = m; markDirty()">{{ m }} 分</button>
          </div>
        </div>
        <div v-else class="field">
          <span>每天查房的時間點</span>
          <div class="times">
            <span v-for="t in form.times" :key="t" class="time-chip">{{ t }}<button title="移除" @click="removeTime(t)">×</button></span>
            <span v-if="!form.times.length" class="muted">尚未設定時間點</span>
          </div>
          <div class="row" style="margin-top: 4px">
            <input v-model="newTime" class="input" type="time" style="width: 140px" />
            <button class="btn btn-sm" @click="addTime">＋ 加入時間點</button>
          </div>
        </div>
        <div class="field">
          <span>
            只在特定時段查房
            <label class="switch" style="vertical-align: middle; margin-left: 6px"><input v-model="form.window_enabled" type="checkbox" /><span /></label>
          </span>
          <div class="row">
            <input v-model="form.window_start" class="input" type="time" style="width: 130px" /> 到
            <input v-model="form.window_end" class="input" type="time" style="width: 130px" />
          </div>
        </div>
        <div class="grid-2">
          <label class="field">
            <span>查房範圍</span>
            <select v-model="form.scope" class="input">
              <option value="all">全部病人</option>
              <option value="OR">只查手術室</option>
              <option value="PACU">只查恢復室</option>
            </select>
          </label>
          <label class="field">
            <span>AI 撰寫查房摘要</span>
            <select v-model="form.ai_summary" class="input">
              <option value="when_findings">有異常時才用 AI（建議）</option>
              <option value="always">每次都用 AI</option>
              <option value="off">不使用 AI（系統範本）</option>
            </select>
          </label>
        </div>
        <label class="field">
          <span>危急病人額外複查 <span class="hint">有危急病人時，在兩次查房之間每隔幾分鐘再看一次這些病人（0＝關閉）</span></span>
          <div class="row">
            <input v-model.number="form.critical_recheck_minutes" class="input" type="number" min="0" max="60" step="0.5" style="width: 120px" />
            <span>分鐘</span>
          </div>
        </label>
        <div class="row">
          <button class="btn btn-primary" @click="save">儲存設定</button>
          <span class="muted">{{ dirty ? '● 有尚未儲存的變更' : '' }}</span>
        </div>
      </div>
      <div>
        <div class="card">
          <div class="card-title">⏱️ 下一次自動查房</div>
          <div class="countdown">{{ countdown }}</div>
          <div class="muted">{{ nextText }}</div>
          <div class="row" style="margin-top: 10px">
            <button class="btn btn-primary" :class="{ busy: runningScope === 'all' }" @click="runNow('all')">▶ 立即查房（全部）</button>
            <button class="btn" :class="{ busy: runningScope === 'OR' }" @click="runNow('OR')">只查手術室</button>
            <button class="btn" :class="{ busy: runningScope === 'PACU' }" @click="runNow('PACU')">只查恢復室</button>
          </div>
        </div>
        <div class="card">
          <div class="card-title">🤖 AI 建議的處置（待您確認） <button class="btn btn-sm btn-ghost" @click="loadActions">↻</button></div>
          <div v-if="!actions.length" class="muted">目前沒有待確認的處置</div>
          <ActionCard v-for="a in actions" :key="a.id" :action="a" @resolved="loadActions" />
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        📋 查房紀錄
        <label class="row" style="font-weight: 500"><input v-model="followLatest" type="checkbox" /> 自動顯示最新一次</label>
      </div>
      <div class="reports">
        <div class="report-list">
          <div v-if="!reports.length" class="empty">尚無查房紀錄</div>
          <div v-for="r in reports" :key="r.id" class="report-item" :class="{ active: r.id === selectedId }" @click="pickReport(r.id)">
            <div class="ri-top"><span>{{ r.trigger_label }}</span><span class="mono">{{ fmtTime(r.wall_time) }}</span></div>
            <div class="ri-sub">
              {{ r.id }}・{{ r.scope }}・{{ r.patients_checked }} 位
              <span v-if="r.n_critical" class="badge badge-crit">危急 {{ r.n_critical }}</span>
              <span v-if="r.n_warning" class="badge badge-warn">警示 {{ r.n_warning }}</span>
              <span v-if="r.summary_source === 'ai'" class="badge badge-info">AI 摘要</span>
              <span v-else-if="r.summary_status === 'pending'" class="badge">AI 撰寫中</span>
            </div>
          </div>
        </div>
        <div>
          <div v-if="!report" class="empty">尚無查房紀錄</div>
          <template v-else>
            <div class="row">
              <b style="font-size: 16px">{{ report.id }}｜{{ report.trigger_label }}</b>
              <span class="muted">查房時間 {{ fmtTime(report.wall_time, true) }}・模擬時間 {{ fmtTime(report.sim_time) }}・{{ report.scope }}・耗時 {{ report.duration_ms }} ms</span>
            </div>
            <div class="kpis">
              <span class="badge">查看 {{ report.patients_checked }} 位</span>
              <span class="badge">工具判讀 {{ report.tools_run }} 次</span>
              <span class="badge badge-crit">危急 {{ report.n_critical }}</span>
              <span class="badge badge-warn">警示 {{ report.n_warning }}</span>
              <span class="badge badge-info">提示 {{ report.n_info }}</span>
              <span class="badge">新問題 {{ report.new_alerts }}</span>
              <span class="badge badge-ok">已緩解 {{ report.resolved_alerts }}</span>
            </div>
            <div class="summary-box">
              <div class="summary-src">
                <template v-if="report.summary_source === 'ai'">🤖 AI 撰寫的查房摘要<template v-if="report.summary_model">（{{ report.summary_model }}）</template></template>
                <template v-else-if="report.summary_status === 'pending'">📄 系統範本摘要 <span class="thinking"><i /><i /><i /> AI 摘要撰寫中</span></template>
                <template v-else>
                  📄 系統範本摘要<span v-if="report.summary_status === 'failed'" class="crit">（AI 摘要失敗：{{ report.summary_error }}）</span>
                </template>
              </div>
              <MarkdownView :source="report.summary_md" />
            </div>
            <details style="margin-top: 10px">
              <summary>逐位病人判讀結果（{{ report.patients.length }} 位有發現）</summary>
              <div v-for="p in report.patients" :key="p.pid" class="prow">
                <div class="prow-head">
                  <span class="sev-dot" :class="sevOf(p.severity).cls" />
                  <a href="#" @click.prevent="openPatient(p.pid)">{{ p.label }}</a>
                  <span v-if="p.new_count" class="badge badge-crit">🆕 新問題</span>
                  <span v-for="s in p.skills" :key="s.id" class="badge">📘 {{ s.name }}</span>
                </div>
                <FindingItem v-for="(f, i) in p.findings" :key="i" :finding="f" />
              </div>
            </details>
          </template>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">🚨 進行中警示 <span class="muted">共 {{ alerts.length }} 項</span></div>
      <div class="table-wrap">
        <div v-if="!alerts.length" class="empty">目前沒有進行中的警示 🎉</div>
        <table v-else>
          <thead>
            <tr><th>嚴重度</th><th>床位</th><th>問題</th><th>內容</th><th>來源工具</th><th>首次出現</th><th>持續查房次數</th><th /></tr>
          </thead>
          <tbody>
            <tr v-for="a in alerts" :key="a.id" class="clickable" @click="openPatient(a.pid)">
              <td><span class="badge" :class="sevOf(a.severity).badge">{{ sevOf(a.severity).label }}</span></td>
              <td><b>{{ a.bed }}</b><br /><span class="faint">{{ a.pid }}</span></td>
              <td>{{ a.title }}</td>
              <td>{{ a.detail }}</td>
              <td class="muted">{{ a.tool_name }}</td>
              <td class="mono">{{ fmtTime(a.first_seen) }}</td>
              <td>{{ a.rounds_seen }}</td>
              <td>
                <span v-if="a.acknowledged" class="ok">✓ 已確認</span>
                <button v-else class="btn btn-sm" @click.stop="ackAlert(a.id)">確認</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>
