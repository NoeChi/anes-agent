<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { NAV_ITEMS } from '@/router'

const route = useRoute()
const router = useRouter()
</script>

<template>
  <nav class="sidebar">
    <button
      v-for="item in NAV_ITEMS"
      :key="item.path"
      :class="{ active: route.path === item.path }"
      @click="router.push(item.path)"
    >
      <span class="nav-icon">{{ item.icon }}</span><span>{{ item.label }}</span>
    </button>
    <div class="nav-foot">決策輔助展示系統<br />非醫療器材，請勿用於真實病人</div>
  </nav>
</template>
