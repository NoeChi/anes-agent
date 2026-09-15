<script setup lang="ts">
import { reactive, ref } from 'vue'
import { api, errMsg } from '@/api/client'
import type { Skill, ToolInfo } from '@/api/types'
import BaseModal from '@/components/BaseModal.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import { toast } from '@/composables/useToast'

const props = defineProps<{ skill: Skill | null; template: string; tools: ToolInfo[] }>()
const emit = defineEmits<{ close: []; saved: [] }>()

const form = reactive({
  name: props.skill?.name ?? '',
  description: props.skill?.description ?? '',
  rounds: props.skill ? props.skill.use_in.includes('rounds') : true,
  chat: props.skill ? props.skill.use_in.includes('chat') : true,
  always: props.skill?.triggers.always ?? false,
  tools: [...(props.skill?.triggers.tools ?? [])],
  keywords: (props.skill?.triggers.keywords ?? []).join(', '),
  body: props.skill?.body ?? props.template,
})
const saving = ref(false)

async function save() {
  const useIn: ('rounds' | 'chat')[] = []
  if (form.rounds) useIn.push('rounds')
  if (form.chat) useIn.push('chat')
  if (!useIn.length) {
    toast('請至少選擇一個使用場合', 'warn')
    return
  }
  saving.value = true
  try {
    const saved = await api.post<Skill>('/api/skills', {
      id: props.skill?.id,
      name: form.name,
      description: form.description,
      enabled: props.skill?.enabled ?? true,
      author: props.skill?.author ?? '使用者',
      use_in: useIn,
      triggers: {
        tools: form.tools,
        keywords: form.keywords.split(/[,，、]/).map((k) => k.trim()).filter(Boolean),
        always: form.always,
      },
      body: form.body,
    })
    toast(`技能「${saved.name}」已儲存`, 'ok')
    emit('saved')
    emit('close')
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <BaseModal :title="skill ? `編輯技能：${skill.name}` : '新增技能'" wide @close="emit('close')">
    <div class="grid-2">
      <label class="field"><span>技能名稱 *</span><input v-model="form.name" class="input" maxlength="40" placeholder="例如：術後譫妄評估" /></label>
      <label class="field">
        <span>什麼時候使用？（一句話，AI 會依此判斷）</span>
        <input v-model="form.description" class="input" maxlength="300" placeholder="例如：恢復室病人躁動或意識混亂時，依本流程評估" />
      </label>
    </div>
    <div class="row" style="gap: 20px; margin-bottom: 8px">
      <label class="check"><input v-model="form.rounds" type="checkbox" /> 查房時使用</label>
      <label class="check"><input v-model="form.chat" type="checkbox" /> 對話時使用</label>
      <label class="check"><input v-model="form.always" type="checkbox" /> 每次查房都套用（適合報告格式類技能）</label>
    </div>
    <div class="field">
      <span>觸發工具 <span class="hint">查房時，這些工具對病人有發現就套用此技能</span></span>
      <div class="checklist-grid">
        <label v-for="t in tools" :key="t.id"><input v-model="form.tools" type="checkbox" :value="t.id" /> {{ t.name }}</label>
      </div>
    </div>
    <label class="field">
      <span>關鍵字 <span class="hint">用逗號分隔；對話內容或查房發現含有這些字時套用</span></span>
      <input v-model="form.keywords" class="input" placeholder="例如：譫妄, 躁動, 意識混亂" />
    </label>
    <div class="field">
      <span>技能內容（Markdown，用一般文字撰寫即可）</span>
      <div class="editor">
        <textarea v-model="form.body" class="input" />
        <div class="preview"><MarkdownView :source="form.body" empty="預覽會顯示在這裡" /></div>
      </div>
    </div>
    <template #footer>
      <button class="btn" @click="emit('close')">取消</button>
      <button class="btn btn-primary" :class="{ busy: saving }" @click="save">💾 儲存技能</button>
    </template>
  </BaseModal>
</template>
