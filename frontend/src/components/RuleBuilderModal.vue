<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errMsg } from '@/api/client'
import type { Location, RuleCatalog, RuleCondition, RuleField, RuleSpec, RuleTestResult, Severity } from '@/api/types'
import BaseModal from '@/components/BaseModal.vue'
import { toast } from '@/composables/useToast'

interface EditableCondition {
  key: number
  field: string
  op: string
  value: string
  duration: number
  window: number
}

const props = defineProps<{ spec: RuleSpec | null }>()
const emit = defineEmits<{ close: []; saved: [] }>()

const COMPARE_OPS = ['>', '>=', '<', '<=', '==', '!=']
const catalog = ref<RuleCatalog | null>(null)
const loadError = ref('')
const conditions = ref<EditableCondition[]>([])
const testResult = ref<RuleTestResult | null>(null)
const testError = ref('')
const saving = ref(false)
let keySeq = 0

const form = reactive({
  name: props.spec?.name ?? '',
  description: props.spec?.description ?? '',
  severity: (props.spec?.severity ?? 'warning') as Severity,
  logic: (props.spec?.logic ?? 'all') as 'all' | 'any',
  or: (props.spec?.locations ?? ['OR', 'PACU']).includes('OR'),
  pacu: (props.spec?.locations ?? ['OR', 'PACU']).includes('PACU'),
  message: props.spec?.message ?? '',
  suggestion: props.spec?.suggestion ?? '',
})

const fieldMap = computed<Record<string, RuleField>>(() => Object.fromEntries((catalog.value?.fields ?? []).map((f) => [f.key, f])))
const groups = computed(() => {
  const out: { name: string; fields: RuleField[] }[] = []
  for (const f of catalog.value?.fields ?? []) {
    let g = out.find((x) => x.name === f.group)
    if (!g) {
      g = { name: f.group, fields: [] }
      out.push(g)
    }
    g.fields.push(f)
  }
  return out
})

function opsFor(field: string): [string, string][] {
  const f = fieldMap.value[field]
  return f && catalog.value ? catalog.value.operators[f.type] : []
}

function extraFor(c: EditableCondition): 'window' | 'duration' | '' {
  if (c.op === 'rises_by' || c.op === 'falls_by') return 'window'
  if (fieldMap.value[c.field]?.history && COMPARE_OPS.includes(c.op)) return 'duration'
  return ''
}

function addCondition(c: RuleCondition) {
  conditions.value.push({
    key: ++keySeq,
    field: c.field,
    op: c.op,
    value: c.value == null ? '' : String(c.value),
    duration: c.duration_min ?? 0,
    window: c.window_min ?? 10,
  })
}

function onFieldChange(c: EditableCondition) {
  const ops = opsFor(c.field)
  c.op = ops[0]?.[0] ?? '>'
  const f = fieldMap.value[c.field]
  c.value = f?.type === 'select' ? (f.options?.[0]?.[0] ?? '') : ''
}

function removeCondition(key: number) {
  conditions.value = conditions.value.filter((c) => c.key !== key)
}

function collect(): RuleSpec {
  const locations: Location[] = []
  if (form.or) locations.push('OR')
  if (form.pacu) locations.push('PACU')
  const spec: RuleSpec = {
    name: form.name,
    description: form.description,
    severity: form.severity,
    logic: form.logic,
    locations,
    message: form.message,
    suggestion: form.suggestion,
    conditions: conditions.value.map((c) => {
      const out: RuleCondition = { field: c.field, op: c.op }
      if (fieldMap.value[c.field]?.type !== 'bool') out.value = c.value
      const extra = extraFor(c)
      if (extra === 'duration' && Number(c.duration) > 0) out.duration_min = Number(c.duration)
      if (extra === 'window') out.window_min = Number(c.window)
      return out
    }),
  }
  if (props.spec?.id) spec.id = props.spec.id
  return spec
}

async function test() {
  testError.value = ''
  try {
    testResult.value = await api.post<RuleTestResult>('/api/rules/test', collect())
  } catch (e) {
    testResult.value = null
    testError.value = errMsg(e)
  }
}

async function save() {
  saving.value = true
  try {
    const saved = await api.post<RuleSpec>('/api/rules', collect())
    toast(`規則「${saved.name}」已儲存，下次查房開始檢查`, 'ok')
    emit('saved')
    emit('close')
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    catalog.value = await api.get<RuleCatalog>('/api/rules/catalog')
  } catch (e) {
    loadError.value = errMsg(e)
    return
  }
  const initial = props.spec?.conditions?.length ? props.spec.conditions : [{ field: 'sbp', op: '>', value: 160, duration_min: 3 }]
  initial.forEach(addCondition)
})
</script>

<template>
  <BaseModal :title="spec ? `編輯規則：${spec.name}` : '新增自訂規則（免寫程式）'" wide @close="emit('close')">
    <div class="help">用下拉選單組合條件，不需要寫程式。儲存後，AI 每次查房都會對每位病人檢查這條規則，符合就產生提醒。</div>
    <div v-if="loadError" class="crit">{{ loadError }}</div>
    <div v-else-if="!catalog" class="muted">載入中…</div>
    <template v-else>
      <div class="grid-2">
        <label class="field"><span>規則名稱 *</span><input v-model="form.name" class="input" maxlength="40" placeholder="例如：高齡病人心跳過快" /></label>
        <label class="field"><span>說明（為什麼要注意）</span><input v-model="form.description" class="input" maxlength="300" /></label>
      </div>
      <div class="row" style="gap: 24px; margin-bottom: 10px">
        <div class="field">
          <span>嚴重度</span>
          <div class="seg">
            <button :class="{ active: form.severity === 'info' }" @click="form.severity = 'info'">🔵 提示</button>
            <button :class="{ active: form.severity === 'warning' }" @click="form.severity = 'warning'">🟠 警示</button>
            <button :class="{ active: form.severity === 'critical' }" @click="form.severity = 'critical'">🔴 危急</button>
          </div>
        </div>
        <div class="field">
          <span>適用區域</span>
          <div>
            <label class="check"><input v-model="form.or" type="checkbox" /> 手術室</label>
            <label class="check"><input v-model="form.pacu" type="checkbox" /> 恢復室</label>
          </div>
        </div>
        <div class="field">
          <span>條件組合</span>
          <div class="seg">
            <button :class="{ active: form.logic === 'all' }" @click="form.logic = 'all'">全部條件都符合</button>
            <button :class="{ active: form.logic === 'any' }" @click="form.logic = 'any'">任一條件符合</button>
          </div>
        </div>
      </div>
      <div class="field"><span>條件</span></div>
      <div class="conds">
        <div v-for="(c, idx) in conditions" :key="c.key" class="cond">
          <span class="n">{{ idx + 1 }}</span>
          <select v-model="c.field" class="input" @change="onFieldChange(c)">
            <optgroup v-for="g in groups" :key="g.name" :label="g.name">
              <option v-for="f in g.fields" :key="f.key" :value="f.key">{{ f.label }}{{ f.unit ? `（${f.unit}）` : '' }}</option>
            </optgroup>
          </select>
          <select v-model="c.op" class="input">
            <option v-for="[v, l] in opsFor(c.field)" :key="v" :value="v">{{ l }}</option>
          </select>
          <span>
            <span v-if="fieldMap[c.field]?.type === 'bool'" class="muted">（不需填值）</span>
            <select v-else-if="fieldMap[c.field]?.type === 'select'" v-model="c.value" class="input">
              <option v-for="[v, l] in fieldMap[c.field]?.options ?? []" :key="v" :value="v">{{ l }}</option>
            </select>
            <input
              v-else-if="fieldMap[c.field]?.type === 'number'"
              v-model="c.value"
              class="input"
              type="number"
              step="any"
              :placeholder="`數值${fieldMap[c.field]?.unit ? '（' + fieldMap[c.field]?.unit + '）' : ''}`"
            />
            <input v-else v-model="c.value" class="input" placeholder="文字" />
          </span>
          <span class="extra">
            <template v-if="extraFor(c) === 'window'">時間窗 <input v-model.number="c.window" class="input" type="number" min="1" max="60" /> 分鐘</template>
            <template v-else-if="extraFor(c) === 'duration'">持續 <input v-model.number="c.duration" class="input" type="number" min="0" max="60" step="0.5" /> 分鐘</template>
          </span>
          <button class="btn btn-sm btn-ghost" type="button" title="刪除條件" @click="removeCondition(c.key)">✕</button>
        </div>
      </div>
      <button class="btn btn-sm" type="button" @click="addCondition({ field: 'hr', op: '>', value: '' })">＋ 新增條件</button>
      <div class="grid-2" style="margin-top: 10px">
        <label class="field">
          <span>提醒內容 <span class="hint">可留白自動產生；可用 {欄位代碼} 帶入數值，例如 {sbp}、{age}</span></span>
          <input v-model="form.message" class="input" maxlength="300" />
        </label>
        <label class="field"><span>建議處置</span><input v-model="form.suggestion" class="input" maxlength="500" /></label>
      </div>
      <div v-if="testResult || testError" class="test-box">
        <span v-if="testError" class="crit">{{ testError }}</span>
        <template v-else-if="testResult">
          <div><b>規則邏輯：</b>{{ testResult.logic_text }}</div>
          <div style="margin: 4px 0"><b>目前 {{ testResult.checked }} 位病人中，有 {{ testResult.matches.length }} 位符合：</b></div>
          <div v-for="m in testResult.matches.slice(0, 15)" :key="m.pid" class="result-line">
            <b>{{ m.label }}</b><span class="muted">{{ m.values.join('；') }}</span>
          </div>
          <div v-if="!testResult.matches.length" class="muted">目前沒有病人符合（規則仍會在之後的查房持續檢查）</div>
        </template>
      </div>
    </template>
    <template #footer>
      <button class="btn" :disabled="!catalog" @click="test">🔍 測試：目前哪些病人符合</button>
      <button class="btn btn-primary" :class="{ busy: saving }" :disabled="!catalog" @click="save">💾 儲存規則</button>
    </template>
  </BaseModal>
</template>
