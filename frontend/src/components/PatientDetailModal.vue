<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, errMsg } from '@/api/client'
import type { InterventionOption, PatientDetail, ToolResult, Trend } from '@/api/types'
import BaseModal from '@/components/BaseModal.vue'
import FindingItem from '@/components/FindingItem.vue'
import VitalChart from '@/components/VitalChart.vue'
import { confirmDialog } from '@/composables/useDialog'
import { toast } from '@/composables/useToast'
import { useChatStore } from '@/stores/chat'
import { useLiveStore } from '@/stores/live'
import type { ChartOptions, ChartSeries } from '@/utils/chart'
import { fmtTime, sevOf, sexLabel } from '@/utils/format'
import { vitalFlag } from '@/utils/vitals'

const props = defineProps<{ pid: string }>()
const emit = defineEmits<{ close: [] }>()

const chat = useChatStore()
const live = useLiveStore()

const detail = ref<PatientDetail | null>(null)
const trend = ref<Trend | null>(null)
const loadError = ref('')
const minutes = ref(60)
const tab = ref<'tools' | 'actions' | 'record'>('tools')
const results = ref<ToolResult[] | null>(null)
const toolsError = ref('')
const toolsLoading = ref(false)
const toolsTime = ref(0)
const interventions = ref<InterventionOption[] | null>(null)
const note = ref('')
let timer: number | undefined

async function refresh() {
  try {
    const [d, t] = await Promise.all([
      api.get<PatientDetail>(`/api/patients/${props.pid}`),
      api.get<Trend>(`/api/patients/${props.pid}/trend?minutes=${minutes.value}`),
    ])
    detail.value = d
    trend.value = t
    loadError.value = ''
  } catch (e) {
    loadError.value = errMsg(e)
    if (timer) {
      clearInterval(timer)
      timer = undefined
    }
  }
}

async function runTools() {
  toolsLoading.value = true
  toolsError.value = ''
  try {
    results.value = await api.post<ToolResult[]>(`/api/patients/${props.pid}/tools`, {})
    toolsTime.value = live.simTime
  } catch (e) {
    toolsError.value = errMsg(e)
  } finally {
    toolsLoading.value = false
  }
}

onMounted(async () => {
  await refresh()
  void runTools()
  timer = window.setInterval(refresh, 3000)
})
onUnmounted(() => clearInterval(timer))
watch(minutes, refresh)
watch(tab, async (t) => {
  if (t === 'actions' && !interventions.value) {
    try {
      interventions.value = await api.get<InterventionOption[]>('/api/catalog/interventions')
    } catch (e) {
      toast(errMsg(e), 'error')
    }
  }
})

const sev = computed(() => sevOf(detail.value?.status?.severity))

const tiles = computed(() => {
  const d = detail.value
  if (!d) return []
  const v = d.vitals
  const tile = (cls: string, label: string, value: string | number | null, unit: string, key?: string) => ({
    cls,
    label,
    value: value ?? '—',
    unit,
    flag: key ? `flag-${vitalFlag(key, key === 'map' ? v.map : (value as number | null), d) || 'none'}` : '',
  })
  return [
    tile('hr', '心跳 HR', v.hr, '/min', 'hr'),
    tile('bp', `血壓（MAP ${v.map ?? '—'}）`, `${v.sbp ?? '—'}/${v.dbp ?? '—'}`, '', 'map'),
    tile('spo2', '血氧 SpO₂', v.spo2, '%', 'spo2'),
    tile('etco2', 'EtCO₂', v.etco2, 'mmHg', 'etco2'),
    tile('rr', '呼吸 RR', v.rr, '/min', 'rr'),
    tile('temp', '體溫', v.temp, '°C', 'temp'),
    d.location === 'PACU' ? tile('bis', '疼痛分數', v.pain, '/10', 'pain') : tile('bis', 'BIS', v.bis, '', 'bis'),
    tile('rr', '氣道峰壓', v.ppeak, 'cmH₂O'),
    tile('rr', '出血量', d.fluids.ebl_ml, 'mL'),
    tile('rr', '尿量', d.fluids.urine_ml, 'mL'),
  ]
})

const charts = computed<{ key: string; series: ChartSeries[]; options: ChartOptions }[]>(() => {
  const tr = trend.value
  const d = detail.value
  if (!tr || !d) return []
  const list: { key: string; series: ChartSeries[]; options: ChartOptions }[] = [
    { key: 'hr', series: [{ label: 'HR', color: '#12b76a', values: tr.hr ?? [] }], options: { title: '心跳', lines: [{ value: 45 }, { value: 120 }] } },
    {
      key: 'bp',
      series: [
        { label: 'SBP', color: '#f04438', values: tr.sbp ?? [] },
        { label: 'MAP', color: '#b42318', values: tr.map ?? [], width: 2.4 },
        { label: 'DBP', color: '#fda29b', values: tr.dbp ?? [] },
      ],
      options: { title: '血壓', lines: [{ value: 65, color: '#b42318' }] },
    },
    { key: 'spo2', series: [{ label: 'SpO₂', color: '#06aed4', values: tr.spo2 ?? [] }], options: { title: '血氧', minSpan: 6, lines: [{ value: 92 }] } },
    {
      key: 'etco2',
      series: [
        { label: 'EtCO₂', color: '#ca8504', values: tr.etco2 ?? [] },
        { label: 'RR', color: '#667085', values: tr.rr ?? [], width: 1.2 },
      ],
      options: { title: 'EtCO₂／呼吸', lines: [{ value: 50 }] },
    },
    d.location === 'PACU'
      ? { key: 'pain', series: [{ label: '疼痛', color: '#7a5af8', values: tr.pain ?? [] }], options: { title: '疼痛分數', minSpan: 5, lines: [{ value: 7 }] } }
      : {
          key: 'bis',
          series: [{ label: 'BIS', color: '#7a5af8', values: tr.bis ?? [] }],
          options: { title: 'BIS 麻醉深度', empty: '此麻醉方式無 BIS', lines: [{ value: 60, color: '#f79009' }, { value: 40, color: '#f79009' }] },
        },
    { key: 'temp', series: [{ label: 'T', color: '#f79009', values: tr.temp ?? [] }], options: { title: '體溫', decimals: 1, minSpan: 1, lines: [{ value: 36 }] } },
  ]
  return list
})

const grouped = computed(() => {
  const all = results.value ?? []
  return {
    withFindings: all.filter((r) => r.findings.length),
    normal: all.filter((r) => r.applicable && r.ok && !r.findings.length),
    na: all.filter((r) => !r.applicable),
    errors: all.filter((r) => !r.ok),
  }
})

const labHistory = computed(() => [...(detail.value?.lab_history ?? [])].reverse())
const interventionLog = computed(() => [...(detail.value?.interventions ?? [])].reverse())
const notes = computed(() => [...(detail.value?.notes ?? [])].reverse())

function askAi() {
  const d = detail.value
  if (!d) return
  chat.ask(`請評估 ${d.bed}（${d.pid}）目前的狀況：看趨勢、執行工具判讀，並依相關技能給出建議。`)
  emit('close')
}

async function ackAlerts() {
  if (!detail.value) return
  try {
    await api.post('/api/alerts/ack-patient', { pid: detail.value.pid })
    toast('已確認此病人的警示', 'ok')
    await refresh()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function doIntervention(iv: InterventionOption) {
  const d = detail.value
  if (!d) return
  if (!(await confirmDialog('執行模擬處置', `確定要對 ${d.bed}（${d.pid}）執行「${iv.label}」嗎？`, '執行'))) return
  try {
    const res = await api.post<{ message: string }>(`/api/patients/${props.pid}/intervention`, { type: iv.id })
    toast(res.message, 'ok')
    await refresh()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function addNote() {
  const content = note.value.trim()
  if (!content) return
  try {
    await api.post(`/api/patients/${props.pid}/note`, { text: content })
    note.value = ''
    await refresh()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}
</script>

<template>
  <BaseModal title="病人詳細資料" wide @close="emit('close')">
    <div class="pv-head">
      <div v-if="loadError && !detail" class="crit">{{ loadError }}</div>
      <div v-else-if="!detail" class="muted">載入中…</div>
      <template v-else>
        <div>
          <div class="pv-title">
            {{ detail.bed }}｜{{ detail.pid }}｜{{ detail.name }}
            <span class="badge" :class="sev.badge">{{ sev.icon }} {{ sev.label }}</span>
          </div>
          <div class="pv-meta">
            {{ detail.age }} 歲 {{ sexLabel(detail.sex) }}・{{ detail.height_cm }} cm／{{ detail.weight_kg }} kg（BMI {{ detail.bmi }}）・ASA {{ detail.asa }}・{{ detail.surgery }}（{{ detail.specialty }}）
          </div>
          <div class="pv-meta">
            {{ detail.anes_label }}・{{ detail.airway }}・<span class="badge" :class="`phase-${detail.phase}`">{{ detail.phase_label }}</span>
            {{ detail.minutes }} 分鐘・節律：{{ detail.rhythm }}
          </div>
          <div v-if="loadError" class="crit">{{ loadError }}</div>
        </div>
        <div class="row">
          <button class="btn" @click="askAi">💬 請 AI 評估</button>
          <button v-if="detail.alerts.length" class="btn" @click="ackAlerts">✓ 確認此病人警示</button>
        </div>
      </template>
    </div>
    <div v-if="detail" class="pv-body">
      <div>
        <div class="pv-vitals">
          <div v-for="(t, i) in tiles" :key="i" class="vt" :class="[t.cls, t.flag]">
            <span>{{ t.label }}</span><b>{{ t.value }}</b><small>{{ t.unit }}</small>
          </div>
        </div>
        <div class="row" style="justify-content: space-between; margin-bottom: 6px">
          <b>生命徵象趨勢</b>
          <div class="seg">
            <button v-for="m in [30, 60, 120]" :key="m" :class="{ active: minutes === m }" @click="minutes = m">{{ m }} 分</button>
          </div>
        </div>
        <div v-if="trend" class="pv-charts">
          <VitalChart v-for="c in charts" :key="c.key" :ts="trend.t" :series="c.series" :options="c.options" />
        </div>
      </div>
      <div>
        <div class="tabs">
          <button :class="{ active: tab === 'tools' }" @click="tab = 'tools'">🧰 工具判讀</button>
          <button :class="{ active: tab === 'actions' }" @click="tab = 'actions'">💉 模擬處置</button>
          <button :class="{ active: tab === 'record' }" @click="tab = 'record'">📋 病歷資料</button>
        </div>

        <div v-show="tab === 'tools'">
          <div class="row" style="margin-bottom: 8px">
            <span class="muted">判讀時間 {{ fmtTime(toolsTime, true) }}（含停用中的工具）</span>
            <span class="spacer" />
            <button class="btn btn-sm" :class="{ busy: toolsLoading }" @click="runTools">↻ 重新判讀</button>
          </div>
          <div v-if="toolsError" class="crit">{{ toolsError }}</div>
          <div v-else-if="!results" class="muted">執行所有工具中…</div>
          <template v-else>
            <template v-if="grouped.withFindings.length">
              <template v-for="r in grouped.withFindings" :key="r.tool_id">
                <FindingItem v-for="(f, i) in r.findings" :key="i" :finding="f" />
                <div v-if="r.enabled === false" class="faint" style="margin: -4px 0 8px">（此工具目前停用，查房時不會執行）</div>
              </template>
            </template>
            <div v-else class="finding"><div class="finding-title ok">✅ 目前沒有工具發現異常</div></div>
            <details open>
              <summary>其他工具結果（{{ grouped.normal.length }}）</summary>
              <div v-for="r in grouped.normal" :key="r.tool_id" class="result-line"><b>{{ r.tool_name }}</b><span class="muted">{{ r.summary }}</span></div>
            </details>
            <details v-if="grouped.errors.length" open>
              <summary class="crit">執行錯誤（{{ grouped.errors.length }}）</summary>
              <div v-for="r in grouped.errors" :key="r.tool_id" class="result-line"><b>{{ r.tool_name }}</b><span class="crit">{{ r.error }}</span></div>
            </details>
            <details>
              <summary>不適用此病人（{{ grouped.na.length }}）</summary>
              <div v-for="r in grouped.na" :key="r.tool_id" class="result-line"><b>{{ r.tool_name }}</b><span class="faint">{{ r.summary }}</span></div>
            </details>
          </template>
        </div>

        <div v-show="tab === 'actions'">
          <div class="help">在模擬病人身上執行處置，觀察生命徵象如何變化（例如低血壓給升壓劑後血壓回升）。實際效果取決於病人當下的狀況。</div>
          <div v-if="!interventions" class="muted">載入中…</div>
          <div v-else class="iv-grid">
            <button v-for="iv in interventions" :key="iv.id" class="btn" @click="doIntervention(iv)">{{ iv.label }}</button>
          </div>
          <h4>處置紀錄</h4>
          <div v-if="!interventionLog.length" class="muted">尚無處置紀錄</div>
          <table v-else>
            <thead><tr><th>時間</th><th>處置</th><th>執行者</th></tr></thead>
            <tbody>
              <tr v-for="(i, idx) in interventionLog" :key="idx"><td>{{ fmtTime(i.t) }}</td><td>{{ i.label }}</td><td>{{ i.by }}</td></tr>
            </tbody>
          </table>
        </div>

        <div v-show="tab === 'record'">
          <dl class="kv">
            <dt>病歷號</dt><dd>{{ detail.mrn }}（模擬）</dd>
            <dt>共病</dt><dd>{{ detail.comorbidities.join('、') || '無' }}</dd>
            <dt>過敏</dt><dd>{{ detail.allergies.join('、') }}</dd>
            <dt>吸菸／PONV 史</dt><dd>{{ detail.smoker ? '吸菸' : '不吸菸' }}／{{ detail.ponv_history ? '有' : '無' }}</dd>
            <dt>術前基準</dt><dd>BP {{ detail.baseline.sbp }}/{{ detail.baseline.dbp }}、HR {{ detail.baseline.hr }}、SpO₂ {{ detail.baseline.spo2 }}%</dd>
            <dt>預計手術時間</dt><dd>{{ detail.planned_min }} 分鐘（已進行 {{ detail.case_minutes }} 分鐘）</dd>
            <dt>目前用藥</dt><dd><div v-for="drug in detail.drugs" :key="drug">{{ drug }}</div></dd>
            <dt>輸液／出血</dt>
            <dd>
              輸液 {{ detail.fluids.crystalloid_ml }} mL、輸血 {{ detail.fluids.blood_ml }} mL、出血 {{ detail.fluids.ebl_ml }} mL（{{ detail.fluids.ebl_pct }}% EBV）<template v-if="detail.fluids.urine_ml != null">、尿量 {{ detail.fluids.urine_ml }} mL</template>
            </dd>
          </dl>
          <h4>檢驗（血液氣體）</h4>
          <div v-if="!detail.labs" class="muted">尚無檢驗，可在「模擬處置」點「抽血檢驗」。</div>
          <div v-else class="table-wrap">
            <table>
              <thead><tr><th>時間</th><th>pH</th><th>PaCO₂</th><th>PaO₂</th><th>Hb</th><th>K</th><th>血糖</th><th>乳酸</th><th>原因</th></tr></thead>
              <tbody>
                <tr v-for="(l, idx) in labHistory" :key="idx">
                  <td>{{ fmtTime(l.t) }}</td><td>{{ l.ph }}</td><td>{{ l.paco2 }}</td><td>{{ l.pao2 }}</td><td>{{ l.hb }}</td>
                  <td>{{ l.k }}</td><td>{{ l.glucose }}</td><td>{{ l.lactate }}</td><td class="faint">{{ l.reason }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <h4>備註</h4>
          <div v-if="!notes.length" class="muted">尚無備註</div>
          <div v-for="(n, idx) in notes" :key="idx" class="result-line">
            <span class="faint">{{ fmtTime(n.t) }}</span><span>{{ n.text }}</span><span class="faint">— {{ n.by }}</span>
          </div>
          <div class="row" style="margin-top: 6px">
            <input v-model="note" class="input" placeholder="新增備註…" style="flex: 1" @keydown.enter="addNote" />
            <button class="btn" @click="addNote">新增</button>
          </div>
        </div>
      </div>
    </div>
  </BaseModal>
</template>
