<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { isTopModal, popModal, pushModal } from '@/composables/modalStack'

defineProps<{ title: string; wide?: boolean }>()
const emit = defineEmits<{ close: [] }>()

const id = pushModal()

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && isTopModal(id)) emit('close')
}

function onBackdrop(e: MouseEvent) {
  if (e.target === e.currentTarget) emit('close')
}

onMounted(() => document.addEventListener('keydown', onKey))
onUnmounted(() => {
  document.removeEventListener('keydown', onKey)
  popModal(id)
})
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop" @mousedown="onBackdrop">
      <div class="modal" :class="{ 'modal-wide': wide }" role="dialog" aria-modal="true">
        <div class="modal-head">
          <h3>{{ title }}</h3>
          <button class="modal-x" aria-label="關閉" @click="emit('close')">×</button>
        </div>
        <div class="modal-body"><slot /></div>
        <div v-if="$slots.footer" class="modal-foot"><slot name="footer" /></div>
      </div>
    </div>
  </Teleport>
</template>
