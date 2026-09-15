import { createRouter, createWebHistory } from 'vue-router'
import GuideView from './views/GuideView.vue'
import MonitorView from './views/MonitorView.vue'
import RoundsView from './views/RoundsView.vue'
import SettingsView from './views/SettingsView.vue'
import SimView from './views/SimView.vue'
import SkillsView from './views/SkillsView.vue'
import ToolsView from './views/ToolsView.vue'

export const NAV_ITEMS = [
  { path: '/monitor', icon: '📊', label: '即時監控' },
  { path: '/rounds', icon: '🩺', label: 'AI 查房' },
  { path: '/tools', icon: '🧰', label: '工具庫' },
  { path: '/skills', icon: '📘', label: '技能庫' },
  { path: '/sim', icon: '🎬', label: '情境演練' },
  { path: '/settings', icon: '⚙️', label: '設定' },
  { path: '/guide', icon: '❓', label: '使用說明' },
] as const

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/monitor' },
    { path: '/monitor', component: MonitorView },
    { path: '/rounds', component: RoundsView },
    { path: '/tools', component: ToolsView },
    { path: '/skills', component: SkillsView },
    { path: '/sim', component: SimView },
    { path: '/settings', component: SettingsView },
    { path: '/guide', component: GuideView },
    { path: '/:pathMatch(.*)*', redirect: '/monitor' },
  ],
})

export default router
