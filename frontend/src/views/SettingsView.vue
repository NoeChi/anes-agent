<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, errMsg } from '@/api/client'
import type { AppStateResponse, PublicSettings } from '@/api/types'
import { confirmDialog } from '@/composables/useDialog'
import { toast } from '@/composables/useToast'
import { useLiveStore } from '@/stores/live'

const live = useLiveStore()
const state = ref<AppStateResponse | null>(null)
const apiKey = ref('')
const showKey = ref(false)
const testing = ref(false)

const TABLE_LABELS: Record<string, string> = {
  patients: '病人',
  vital_signs: '生命徵象紀錄',
  round_reports: '查房報告',
  alerts: '警示',
  rules: '自訂規則',
  skills: '技能',
  ml_models: 'AI 模型',
  chat_messages: '對話訊息',
}

const llm = computed(() => state.value?.settings.llm)
const sourceText = computed(() => ({ settings: '（網頁設定）', env: '（環境變數 ANTHROPIC_API_KEY）' })[llm.value?.api_key_source ?? ''] ?? '')
const ML_STATE: Record<string, string> = { ready: '就緒', training: '訓練中', error: '錯誤' }
const tables = computed(() => Object.entries(state.value?.db?.tables ?? {}))

async function load() {
  try {
    state.value = await live.refreshState()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function saveLlm(body: Record<string, unknown>, message: string) {
  try {
    live.settings = await api.put<PublicSettings>('/api/settings/llm', body)
    await load()
    toast(message, 'ok')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function saveKey() {
  const key = apiKey.value.trim()
  if (!key) {
    toast('請輸入金鑰', 'warn')
    return
  }
  await saveLlm({ api_key: key }, '金鑰已儲存，AI 助理已切換為 Claude 模式')
  apiKey.value = ''
}

async function clearKey() {
  if (!(await confirmDialog('清除金鑰', '清除後系統會改用離線模式。確定嗎？', '清除', true))) return
  await saveLlm({ api_key: '' }, '已清除金鑰')
}

async function testConnection() {
  testing.value = true
  try {
    const r = await api.post<{ model: string; reply: string }>('/api/llm/test', {})
    toast(`連線成功（${r.model}）：${r.reply}`, 'ok')
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    testing.value = false
  }
}

onMounted(load)
watch(() => live.llm?.available, () => void load())
</script>

<template>
  <section class="page active">
    <div class="page-head">
      <div>
        <h1>設定</h1>
        <p class="muted">AI 模型連線、資料庫與系統資訊。</p>
      </div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">🤖 Claude AI 連線</div>
        <div style="margin-bottom: 10px">
          <template v-if="llm?.api_key_set">
            <span class="pill pill-ok">🤖 已設定金鑰 {{ llm.api_key_hint }} {{ sourceText }}</span>
            <div v-if="state?.llm.last_error" class="crit" style="margin-top: 4px">最近錯誤：{{ state.llm.last_error }}</div>
          </template>
          <span v-else class="pill pill-off">🔌 尚未設定金鑰（離線模式）</span>
        </div>
        <label class="field">
          <span>Claude API 金鑰 <span class="hint">到 console.anthropic.com 申請；金鑰只儲存在這台電腦上的系統中</span></span>
          <div class="row">
            <input v-model="apiKey" class="input" :type="showKey ? 'text' : 'password'" placeholder="sk-ant-…" autocomplete="off" style="flex: 1" />
            <button class="btn btn-sm btn-ghost" type="button" @click="showKey = !showKey">{{ showKey ? '隱藏' : '顯示' }}</button>
          </div>
        </label>
        <div class="row" style="margin-bottom: 12px">
          <button class="btn btn-primary" @click="saveKey">儲存金鑰</button>
          <button class="btn btn-danger-ghost" @click="clearKey">清除金鑰</button>
          <button class="btn" :class="{ busy: testing }" @click="testConnection">🔌 測試連線</button>
        </div>
        <label class="field">
          <span>AI 模型</span>
          <select class="input" :value="llm?.model" @change="saveLlm({ model: ($event.target as HTMLSelectElement).value }, '模型已更新')">
            <option v-for="m in llm?.model_choices ?? []" :key="m.id" :value="m.id">{{ m.label }}</option>
          </select>
        </label>
        <div class="field">
          <span>思考深度</span>
          <div class="seg">
            <button :class="{ active: llm?.effort === 'low' }" @click="saveLlm({ effort: 'low' }, '思考深度已更新')">快速</button>
            <button :class="{ active: llm?.effort === 'medium' }" @click="saveLlm({ effort: 'medium' }, '思考深度已更新')">平衡（建議）</button>
            <button :class="{ active: llm?.effort === 'high' }" @click="saveLlm({ effort: 'high' }, '思考深度已更新')">深入</button>
          </div>
          <span class="hint">越深入回答越完整，但速度較慢、費用較高。</span>
        </div>
      </div>
      <div class="card">
        <div class="card-title">🔌 沒有金鑰也能展示嗎？</div>
        <p>可以。沒有設定金鑰時，系統會以<b>離線模式</b>運作：</p>
        <ul>
          <li>自動查房、所有規則／評分／AI 模型工具都正常運作</li>
          <li>查房摘要改用系統範本產生（仍會套用技能的重點）</li>
          <li>對話改用關鍵字理解常見問題（例如「P012 狀況」「立即查房」「把查房改成每 3 分鐘」）</li>
        </ul>
        <p>設定金鑰後，AI 助理可以理解任何說法、自己決定要呼叫哪些工具、讀取技能後撰寫建議，還能替你建立規則與技能。</p>
      </div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">🗄️ 資料庫</div>
        <template v-if="state?.db">
          <div style="margin-bottom: 8px">
            <span v-if="state.db.ok" class="pill pill-ok">✅ PostgreSQL 已連線</span>
            <span v-else class="pill pill-warn">⚠️ 資料庫連線異常</span>
            <span class="muted" style="margin-left: 8px">{{ state.db.backend }}</span>
          </div>
          <div v-if="tables.length" class="table-wrap">
            <table>
              <thead><tr><th>資料表</th><th>內容</th><th style="text-align: right">筆數</th></tr></thead>
              <tbody>
                <tr v-for="[name, count] in tables" :key="name">
                  <td><code>{{ name }}</code></td>
                  <td>{{ TABLE_LABELS[name] ?? '' }}</td>
                  <td style="text-align: right" class="mono">{{ count.toLocaleString() }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <p v-else class="muted">目前的後端尚未提供資料庫狀態。</p>
        <p class="muted">規則、技能、AI 模型、查房紀錄、警示、對話與即時生命徵象都存在 PostgreSQL 資料庫。</p>
      </div>
      <div class="card">
        <div class="card-title">📁 系統資訊</div>
        <dl v-if="state" class="kv">
          <dt>病人</dt><dd>{{ state.counts.patients }} 位（手術室 {{ state.sim.or }}、恢復室 {{ state.sim.pacu }}）</dd>
          <dt>工具</dt><dd>{{ state.counts.tools }} 個</dd>
          <dt>技能</dt><dd>{{ state.counts.skills }} 個</dd>
          <dt>AI 模型狀態</dt><dd>{{ ML_STATE[state.ml.state] ?? state.ml.state }} {{ state.ml.message }}</dd>
          <dt>Python 外掛</dt><dd><code>backend/plugins/</code></dd>
        </dl>
        <div v-else class="muted">載入中…</div>
      </div>
    </div>
  </section>
</template>
