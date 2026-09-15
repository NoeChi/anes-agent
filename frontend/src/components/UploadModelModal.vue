<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, errMsg } from '@/api/client'
import type { MlCatalog, ModelMeta } from '@/api/types'
import BaseModal from '@/components/BaseModal.vue'
import { toast } from '@/composables/useToast'

const emit = defineEmits<{ close: []; uploaded: [] }>()

const catalog = ref<MlCatalog | null>(null)
const loadError = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const name = ref('')
const targetLabel = ref('')
const order = ref<string[]>([])
const threshold = ref(0.5)
const suggestion = ref('')
const description = ref('')
const uploading = ref(false)

function toggleFeature(key: string, checked: boolean) {
  const idx = order.value.indexOf(key)
  if (checked && idx < 0) order.value.push(key)
  if (!checked && idx >= 0) order.value.splice(idx, 1)
}

async function upload() {
  const file = fileInput.value?.files?.[0]
  if (!file) {
    toast('請選擇模型檔', 'warn')
    return
  }
  const fd = new FormData()
  fd.append('file', file)
  fd.append('name', name.value)
  fd.append('features', JSON.stringify(order.value))
  fd.append('threshold', String(threshold.value))
  fd.append('target_label', targetLabel.value)
  fd.append('description', description.value)
  fd.append('suggestion', suggestion.value)
  uploading.value = true
  try {
    const meta = await api.post<ModelMeta>('/api/ml/upload', fd)
    toast(`模型「${meta.name}」已加入工具庫`, 'ok')
    emit('uploaded')
    emit('close')
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    uploading.value = false
  }
}

onMounted(async () => {
  try {
    catalog.value = await api.get<MlCatalog>('/api/ml/catalog')
  } catch (e) {
    loadError.value = errMsg(e)
  }
})
</script>

<template>
  <BaseModal title="上傳 AI 模型" wide @close="emit('close')">
    <div class="help">
      給有自己模型的研究人員：上傳 scikit-learn 模型（以 joblib 存成 .joblib，需支援 predict_proba），並勾選模型使用的輸入特徵。<b>勾選順序＝模型輸入欄位順序</b>。
    </div>
    <div class="help" style="background: var(--warn-soft); color: #93370d">⚠️ 模型檔可能包含可執行的程式碼，只上傳你信任來源的檔案。</div>
    <div v-if="loadError" class="crit">{{ loadError }}</div>
    <template v-else>
      <label class="field"><span>模型檔（.joblib）*</span><input ref="fileInput" class="input" type="file" accept=".joblib,.pkl" /></label>
      <div class="grid-2">
        <label class="field"><span>模型名稱 *</span><input v-model="name" class="input" maxlength="40" /></label>
        <label class="field"><span>預測目標（例如：30 分鐘內需要輸血）</span><input v-model="targetLabel" class="input" maxlength="60" /></label>
      </div>
      <div class="field">
        <span>輸入特徵（依勾選順序）<span class="hint">{{ order.length ? `順序：${order.join(' → ')}` : '' }}</span></span>
        <div v-if="catalog" class="checklist-grid">
          <label v-for="f in catalog.features" :key="f.key">
            <input type="checkbox" :checked="order.includes(f.key)" @change="toggleFeature(f.key, ($event.target as HTMLInputElement).checked)" />
            {{ f.label }}
          </label>
        </div>
        <div v-else class="muted">載入中…</div>
      </div>
      <div class="grid-2">
        <label class="field"><span>警示門檻（機率 0.05–0.95）</span><input v-model.number="threshold" class="input" type="number" min="0.05" max="0.95" step="0.05" /></label>
        <label class="field"><span>提醒時的建議處置</span><input v-model="suggestion" class="input" maxlength="300" /></label>
      </div>
      <label class="field"><span>說明</span><input v-model="description" class="input" maxlength="300" /></label>
    </template>
    <template #footer>
      <button class="btn btn-primary" :class="{ busy: uploading }" @click="upload">⬆ 上傳並加入工具庫</button>
    </template>
  </BaseModal>
</template>
