<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errMsg } from '@/api/client'
import type { Skill, ToolInfo } from '@/api/types'
import { useWs } from '@/api/ws'
import BaseModal from '@/components/BaseModal.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import SkillEditorModal from '@/components/SkillEditorModal.vue'
import { confirmDialog } from '@/composables/useDialog'
import { toast } from '@/composables/useToast'

const TEMPLATES: Record<string, string> = {
  procedure: `# 技能名稱

## 何時使用
- 描述在什麼情況下，AI 應該依照這份流程

## 評估步驟
1. 先確認哪些數值或趨勢
2. 需要排除哪些原因

## 建議處置
- 第一步處置（藥物、劑量、操作）
- 第二步處置

## 回報重點
- AI 回報時一定要包含的數值與資訊
`,
  report: `# 報告格式名稱

## 報告結構
1. 一句話總覽
2. 依嚴重度排序的病人清單（每位：發現、可能原因、建議）
3. 其餘穩定病人人數

## 撰寫原則
- 只能使用工具提供的數據，不可編造
- 使用繁體中文、條列、數值附單位
`,
  blank: '',
}

const skills = ref<Skill[]>([])
const tools = ref<ToolInfo[]>([])
// undefined＝關閉；null＝新增
const editing = ref<Skill | null | undefined>(undefined)
const template = ref('')
const viewing = ref<Skill | null>(null)

const toolName = computed<Record<string, string>>(() => Object.fromEntries(tools.value.map((t) => [t.id, t.name])))

async function load() {
  try {
    ;[skills.value, tools.value] = await Promise.all([api.get<Skill[]>('/api/skills'), api.get<ToolInfo[]>('/api/tools')])
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

onMounted(load)
useWs('skills_changed', () => void load())

function newSkill(kind: string) {
  template.value = TEMPLATES[kind] ?? ''
  editing.value = null
}

function preview(body: string) {
  return body.split('\n').slice(0, 14).join('\n')
}

async function toggle(s: Skill, e: Event) {
  const enabled = (e.target as HTMLInputElement).checked
  try {
    await api.post('/api/skills', { ...s, enabled })
    toast(enabled ? '技能已啟用' : '技能已停用', 'ok')
    await load()
  } catch (err) {
    toast(errMsg(err), 'error')
  }
}

async function remove(s: Skill) {
  if (!(await confirmDialog('刪除技能', `確定要刪除「${s.name}」嗎？`, '刪除', true))) return
  try {
    await api.del(`/api/skills/${s.id}`)
    toast('已刪除', 'ok')
    await load()
  } catch (err) {
    toast(errMsg(err), 'error')
  }
}
</script>

<template>
  <section class="page active">
    <div class="page-head">
      <div>
        <h1>技能庫</h1>
        <p class="muted">「技能」是寫給 AI 看的標準作業流程（SOP）。用一般文字撰寫即可：AI 查房發現特定問題時，會依照對應技能給出建議；對話時也會先讀取相關技能再回答。</p>
      </div>
      <div class="row">
        <button class="btn btn-primary" @click="newSkill('procedure')">＋ 新增處置流程技能</button>
        <button class="btn" @click="newSkill('report')">＋ 新增報告格式技能</button>
        <button class="btn btn-ghost" @click="newSkill('blank')">＋ 空白技能</button>
      </div>
    </div>
    <div class="help">💡 設定「觸發工具」後，查房時只要該工具對病人有發現，AI 就會套用這份技能。例如「術中低血壓處置」技能綁定「低血壓偵測」與「低血壓預測 AI」。</div>
    <div class="tgrid">
      <div v-for="s in skills" :key="s.id" class="tcard" :class="{ disabled: !s.enabled }">
        <div class="tcard-head">
          <span class="cat cat-rule">📘 技能</span>
          <h3>{{ s.name }}</h3>
          <label class="switch" title="啟用／停用"><input type="checkbox" :checked="s.enabled" @change="toggle(s, $event)" /><span /></label>
        </div>
        <p>{{ s.description }}</p>
        <div class="metrics">
          <span v-if="s.triggers.always" class="badge badge-info">每次查房都套用</span>
          <span v-for="t in s.triggers.tools" :key="t" class="badge">🧰 {{ toolName[t] ?? t }}</span>
          <span v-for="k in s.triggers.keywords.slice(0, 6)" :key="k" class="badge">🔑 {{ k }}</span>
        </div>
        <div class="faint">
          使用場合：{{ s.use_in.map((u) => (u === 'rounds' ? '查房' : '對話')).join('、') }}・作者：{{ s.author }}{{ s.updated_at ? '・更新 ' + s.updated_at : '' }}
        </div>
        <div class="skill-body"><MarkdownView :source="preview(s.body)" /></div>
        <div class="tcard-foot">
          <button class="btn btn-sm" @click="viewing = s">閱讀全文</button>
          <button class="btn btn-sm" @click="editing = s">編輯</button>
          <span class="spacer" />
          <button class="btn btn-sm btn-danger-ghost" @click="remove(s)">刪除</button>
        </div>
      </div>
      <div v-if="!skills.length" class="empty">還沒有技能</div>
    </div>
    <SkillEditorModal v-if="editing !== undefined" :skill="editing" :template="template" :tools="tools" @close="editing = undefined" @saved="load" />
    <BaseModal v-if="viewing" :title="viewing.name" wide @close="viewing = null">
      <MarkdownView :source="viewing.body" />
    </BaseModal>
  </section>
</template>
