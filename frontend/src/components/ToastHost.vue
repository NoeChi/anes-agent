<script setup lang="ts">
import { dismissToast, toasts, type ToastItem } from '@/composables/useToast'

function run(t: ToastItem) {
  t.action?.onClick()
  dismissToast(t.id)
}
</script>

<template>
  <Teleport to="body">
    <div id="toasts">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="`toast-${t.type}`">
        <div class="toast-msg">{{ t.message }}</div>
        <button v-if="t.action" class="btn btn-sm" @click="run(t)">{{ t.action.label }}</button>
        <button class="toast-x" @click="dismissToast(t.id)">×</button>
      </div>
    </div>
  </Teleport>
</template>
