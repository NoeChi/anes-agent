<script setup lang="ts">
import { computed } from 'vue'
import BaseModal from '@/components/BaseModal.vue'
import { answerConfirm, confirmRequest } from '@/composables/useDialog'

const req = computed(() => confirmRequest.value)
</script>

<template>
  <BaseModal v-if="req" :title="req.title" @close="answerConfirm(false)">
    <p>{{ req.message }}</p>
    <template #footer>
      <button class="btn" @click="answerConfirm(false)">取消</button>
      <button class="btn" :class="req.danger ? 'btn-danger' : 'btn-primary'" @click="answerConfirm(true)">{{ req.okLabel }}</button>
    </template>
  </BaseModal>
</template>
