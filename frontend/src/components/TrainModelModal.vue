<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errMsg } from '@/api/client'
import type { MlCatalog, ModelMeta } from '@/api/types'
import BaseModal from '@/components/BaseModal.vue'
import { toast } from '@/composables/useToast'
import { useLiveStore } from '@/stores/live'
import { pct } from '@/utils/format'

const emit = defineEmits<{ close: []; trained: [] }>()
const live = useLiveStore()

const catalog = ref<MlCatalog | null>(null)
const loadError = ref('')
const name = ref('')
const target = ref('')
const algorithm = ref('gbt')
const selected = ref<string[]>([])
const autoThreshold = ref(true)
const threshold = ref(0.5)
const description = ref('')
const training = ref(false)
const result = ref<ModelMeta | null>(null)
const trainError = ref('')

const groups = computed(() => {
  const out: { name: string; features: MlCatalog['features'] }[] = []
  for (const f of catalog.value?.features ?? []) {
    let g = out.find((x) => x.name === f.group)
    if (!g) {
      g = { name: f.group, features: [] }
      out.push(g)
    }
    g.features.push(f)
  }
  return out
})

const progressMessage = computed(() =>
  live.ml?.state === 'training' && live.ml.message ? live.ml.message : '訓練中…（第一次訓練需要先產生訓練資料，約 20–60 秒）',
)
const progressWidth = computed(() => `${Math.max(5, Math.round((live.ml?.state === 'training' ? live.ml.progress : 0) * 100))}%`)

function useRecommended() {
  const t = catalog.value?.targets.find((x) => x.id === target.value)
  selected.value = t ? [...t.default_features] : []
}

function selectAll() {
  selected.value = (catalog.value?.features ?? []).map((f) => f.key)
}

const aucWord = computed(() => {
  const auc = result.value?.metrics.auc
  if (auc == null) return ''
  return auc >= 0.9 ? '優秀' : auc >= 0.8 ? '良好' : auc >= 0.7 ? '尚可' : '需要改進，可嘗試其他特徵或演算法'
})

async function train() {
  if (!name.value.trim()) {
    toast('請輸入模型名稱', 'warn')
    return
  }
  if (!selected.value.length) {
    toast('請至少選擇一個特徵', 'warn')
    return
  }
  training.value = true
  trainError.value = ''
  result.value = null
  try {
    const meta = await api.post<ModelMeta>('/api/ml/train', {
      name: name.value,
      features: selected.value,
      description: description.value,
      target: target.value,
      algorithm: algorithm.value,
      threshold: autoThreshold.value ? null : Number(threshold.value),
    })
    result.value = meta
    toast(`模型「${meta.name}」已加入工具庫`, 'ok')
    emit('trained')
  } catch (e) {
    trainError.value = errMsg(e)
  } finally {
    training.value = false
  }
}

onMounted(async () => {
  try {
    catalog.value = await api.get<MlCatalog>('/api/ml/catalog')
    target.value = catalog.value.targets[0]?.id ?? ''
    useRecommended()
  } catch (e) {
    loadError.value = errMsg(e)
  }
})
</script>

<template>
  <BaseModal title="訓練 AI 模型（免寫程式）" wide @close="emit('close')">
    <div class="help">
      不用寫程式：選擇「要預測什麼」、「模型可以看哪些資料」與「演算法」，系統會用模擬器產生的歷史資料訓練，並用<b>訓練時沒看過的病人</b>測試準確度。完成後自動加入工具庫，查房時就會使用。
    </div>
    <div v-if="loadError" class="crit">{{ loadError }}</div>
    <div v-else-if="!catalog" class="muted">載入中…</div>
    <template v-else>
      <div class="grid-2">
        <label class="field"><span>模型名稱 *</span><input v-model="name" class="input" maxlength="40" placeholder="例如：低血氧預警模型" /></label>
        <label class="field">
          <span>要預測什麼？</span>
          <select v-model="target" class="input" @change="useRecommended">
            <option v-for="t in catalog.targets" :key="t.id" :value="t.id">{{ t.label }}</option>
          </select>
        </label>
      </div>
      <div class="field">
        <span>使用哪種演算法？</span>
        <div class="algo-grid">
          <label v-for="a in catalog.algorithms" :key="a.id" class="algo" :class="{ active: algorithm === a.id }">
            <input v-model="algorithm" type="radio" name="tr-algo" :value="a.id" />
            <div>
              <b>{{ a.label }}</b>
              <span class="cat" :class="a.family === 'dl' ? 'cat-dl' : 'cat-ml'">{{ a.family === 'dl' ? '深度學習' : '機器學習' }}</span>
              <small>{{ a.desc }}</small>
            </div>
          </label>
        </div>
      </div>
      <div class="field">
        <span>
          模型可以看哪些資料（特徵）？
          <button class="btn btn-sm" type="button" @click="useRecommended">使用建議特徵</button>
          <button class="btn btn-sm btn-ghost" type="button" @click="selectAll">全選</button>
          <button class="btn btn-sm btn-ghost" type="button" @click="selected = []">清除</button>
          <span class="hint">已選 {{ selected.length }} 項</span>
        </span>
        <div class="feat-groups">
          <div v-for="g in groups" :key="g.name" class="g">
            <b>{{ g.name }}</b>
            <label v-for="f in g.features" :key="f.key"><input v-model="selected" type="checkbox" :value="f.key" /> {{ f.label }}</label>
          </div>
        </div>
      </div>
      <div class="field">
        <span>警示門檻</span>
        <label class="check"><input v-model="autoThreshold" type="checkbox" /> 由系統自動建議（在特異度至少 95% 的前提下，盡量提高敏感度，減少誤報）</label>
        <div v-if="!autoThreshold" class="slider-row">
          <input v-model.number="threshold" type="range" min="0.05" max="0.95" step="0.05" /><b>{{ Math.round(threshold * 100) }}%</b>
        </div>
      </div>
      <label class="field"><span>說明（選填）</span><input v-model="description" class="input" maxlength="300" /></label>
      <div v-if="training">
        <div class="muted">{{ progressMessage }}</div>
        <div class="progress"><div :style="{ width: progressWidth }" /></div>
      </div>
      <div v-if="trainError" class="crit">訓練失敗：{{ trainError }}</div>
      <div v-if="result" class="result-card">
        <h3>✅「{{ result.name }}」訓練完成，已加入工具庫</h3>
        <p>用 <b>{{ result.metrics.patients_test }}</b> 位訓練時沒看過的病人（{{ (result.metrics.n_test ?? 0).toLocaleString() }} 個時間點）測試：</p>
        <ul>
          <li><b>AUC {{ result.metrics.auc ?? '—' }}</b>：整體分辨能力，0.5 等於亂猜、越接近 1 越好（{{ aucWord }}）。</li>
          <li><b>敏感度 {{ pct(result.metrics.sensitivity) }}</b>：真的會發生時，模型事先提醒的比例。</li>
          <li><b>特異度 {{ pct(result.metrics.specificity) }}</b>：不會發生時，模型沒有誤報的比例。</li>
          <li><b>陽性預測值 {{ pct(result.metrics.ppv) }}</b>：模型發出提醒時，真的發生的比例（事件越罕見，這個數字越低）。</li>
          <li>
            警示門檻 {{ pct(result.metrics.threshold) }}（系統建議 {{ pct(result.metrics.suggested_threshold) }}）・訓練資料中事件比例
            {{ pct(result.metrics.prevalence) }}・訓練耗時 {{ result.metrics.train_seconds }} 秒
          </li>
        </ul>
        <p v-if="result.metrics.importance?.length">
          模型最看重的資料：{{ result.metrics.importance.map((i) => `${i.label}（${Math.round(i.weight * 100)}%）`).join('、') }}
        </p>
      </div>
    </template>
    <template #footer>
      <button class="btn" @click="emit('close')">關閉</button>
      <button class="btn btn-primary" :class="{ busy: training }" :disabled="!catalog" @click="train">🧠 開始訓練</button>
    </template>
  </BaseModal>
</template>
