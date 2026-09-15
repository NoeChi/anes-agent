<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, errMsg } from '@/api/client'
import type { RuleSpec, ToolInfo, ToolResult } from '@/api/types'
import FindingItem from '@/components/FindingItem.vue'
import { confirmDialog } from '@/composables/useDialog'
import { toast } from '@/composables/useToast'
import { useLiveStore } from '@/stores/live'
import { CATEGORY, locationLabel } from '@/utils/format'

const props = defineProps<{ tool: ToolInfo }>()
const emit = defineEmits<{ edit: [spec: RuleSpec]; changed: [] }>()
const live = useLiveStore()

const params = ref<Record<string, number | string | boolean>>({})
const pid = ref('')
const tryResult = ref<ToolResult | null>(null)
const tryError = ref('')
const trying = ref(false)

watch(() => props.tool.param_values, (v) => {
  params.value = { ...v }
}, { immediate: true })

watch(() => live.patients.length, () => {
  if (!pid.value && live.patients[0]) pid.value = live.patients[0].pid
}, { immediate: true })

const cat = computed(() => CATEGORY[props.tool.category] ?? { label: props.tool.category_label, cls: '' })
const where = computed(() => props.tool.locations.map(locationLabel).join('、'))
const metrics = computed(() => {
  const m = props.tool.model?.metrics
  if (!m) return []
  const chips: string[] = []
  if (m.auc != null) chips.push(`AUC ${m.auc}`)
  if (m.sensitivity != null) chips.push(`敏感度 ${Math.round(m.sensitivity * 100)}%`)
  if (m.specificity != null) chips.push(`特異度 ${Math.round(m.specificity * 100)}%`)
  if (m.n_train) chips.push(`訓練樣本 ${m.n_train.toLocaleString()}`)
  if (m.patients_test) chips.push(`測試病人 ${m.patients_test}`)
  return chips
})
const deletable = computed(() => !props.tool.builtin && props.tool.category !== 'plugin')

async function toggle(e: Event) {
  const enabled = (e.target as HTMLInputElement).checked
  try {
    await api.put(`/api/tools/${props.tool.id}`, { enabled })
    toast(enabled ? '已啟用，下次查房會執行此工具' : '已停用，查房時不會執行此工具', 'ok')
    emit('changed')
  } catch (err) {
    toast(errMsg(err), 'error')
  }
}

async function saveParams(reset: boolean) {
  const body: Record<string, number | string | boolean> = {}
  for (const p of props.tool.params) body[p.key] = reset ? p.default : Number(params.value[p.key])
  try {
    await api.put(`/api/tools/${props.tool.id}`, { params: body })
    toast(reset ? '已恢復預設門檻' : '門檻已儲存，下次查房生效', 'ok')
    emit('changed')
  } catch (err) {
    toast(errMsg(err), 'error')
  }
}

async function tryRun() {
  if (!pid.value) return
  trying.value = true
  tryError.value = ''
  try {
    const [r] = await api.post<ToolResult[]>(`/api/patients/${pid.value}/tools`, { tool_ids: [props.tool.id] })
    tryResult.value = r ?? null
  } catch (err) {
    tryResult.value = null
    tryError.value = errMsg(err)
  } finally {
    trying.value = false
  }
}

async function remove() {
  if (!(await confirmDialog('刪除工具', `確定要刪除「${props.tool.name}」嗎？刪除後無法復原。`, '刪除', true))) return
  try {
    await api.del(`/api/tools/${props.tool.id}`)
    toast('已刪除', 'ok')
    emit('changed')
  } catch (err) {
    toast(errMsg(err), 'error')
  }
}
</script>

<template>
  <div class="tcard" :class="{ disabled: !tool.enabled }">
    <div class="tcard-head">
      <span class="cat" :class="cat.cls">{{ cat.label }}</span>
      <h3>{{ tool.name }}</h3>
      <label class="switch" title="啟用／停用（停用後查房不會執行）"><input type="checkbox" :checked="tool.enabled" @change="toggle" /><span /></label>
    </div>
    <p>{{ tool.description }}</p>
    <div v-if="metrics.length" class="metrics"><span v-for="m in metrics" :key="m" class="badge">{{ m }}</span></div>
    <details>
      <summary>運作方式</summary>
      <p class="muted">{{ tool.how_it_works }}</p>
      <p class="faint">適用：{{ where }}・代碼：<code>{{ tool.id }}</code></p>
      <p v-if="tool.model" class="muted" style="margin-top: 4px">
        預測目標：{{ tool.model.target_label ?? '' }}<br />訓練時間：{{ tool.model.trained_at ?? '' }}・輸入特徵 {{ tool.model.features.length }} 項
      </p>
    </details>
    <template v-if="tool.params.length">
      <div class="params">
        <label v-for="p in tool.params" :key="p.key">
          {{ p.label }}{{ p.unit ? `（${p.unit}）` : '' }}
          <input v-model="params[p.key]" type="number" :min="p.min ?? undefined" :max="p.max ?? undefined" :step="p.step ?? 'any'" />
        </label>
      </div>
      <div class="row">
        <button class="btn btn-sm" @click="saveParams(false)">儲存門檻</button>
        <button class="btn btn-sm btn-ghost" @click="saveParams(true)">恢復預設</button>
      </div>
    </template>
    <div class="tcard-foot">
      <select v-model="pid">
        <option v-for="p in live.patients" :key="p.pid" :value="p.pid">{{ p.bed }}｜{{ p.pid }}｜{{ p.surgery }}</option>
      </select>
      <button class="btn btn-sm" :class="{ busy: trying }" @click="tryRun">▶ 試跑</button>
      <span class="spacer" />
      <button v-if="tool.category === 'custom_rule' && tool.spec" class="btn btn-sm" @click="emit('edit', tool.spec)">編輯</button>
      <button v-if="deletable" class="btn btn-sm btn-danger-ghost" @click="remove">刪除</button>
    </div>
    <div v-if="tryResult || tryError" class="try-result">
      <span v-if="tryError" class="crit">{{ tryError }}</span>
      <span v-else-if="tryResult && !tryResult.applicable" class="muted">不適用此病人：{{ tryResult.summary }}</span>
      <span v-else-if="tryResult && !tryResult.ok" class="crit">錯誤：{{ tryResult.error }}</span>
      <template v-else-if="tryResult">
        <div><b>結果：</b>{{ tryResult.summary }}</div>
        <FindingItem v-for="(f, i) in tryResult.findings" :key="i" :finding="f" />
        <div v-if="!tryResult.findings.length" class="ok">未發現異常</div>
      </template>
    </div>
  </div>
</template>
