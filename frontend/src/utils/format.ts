import type { Category, PatientStatus } from '@/api/types'

export const pad = (n: number): string => String(n).padStart(2, '0')

export function fmtTime(ts: number | null | undefined, sec = false): string {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}${sec ? ':' + pad(d.getSeconds()) : ''}`
}

export function fmtCountdown(s: number | null | undefined): string {
  if (s == null) return '-'
  const total = Math.max(0, Math.round(s))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const x = total % 60
  return h ? `${h}:${pad(m)}:${pad(x)}` : `${pad(m)}:${pad(x)}`
}

export interface SevMeta {
  label: string
  icon: string
  cls: string
  badge: string
}

export const SEV: Record<PatientStatus, SevMeta> = {
  critical: { label: '危急', icon: '🔴', cls: 'crit', badge: 'badge-crit' },
  warning: { label: '警示', icon: '🟠', cls: 'warn', badge: 'badge-warn' },
  info: { label: '提示', icon: '🔵', cls: 'info', badge: 'badge-info' },
  normal: { label: '穩定', icon: '🟢', cls: 'ok', badge: 'badge-ok' },
  unchecked: { label: '尚未查房', icon: '⚪', cls: 'none', badge: '' },
}

export function sevOf(s: string | null | undefined): SevMeta {
  return SEV[(s ?? 'unchecked') as PatientStatus] ?? SEV.unchecked
}

export const CATEGORY: Record<Category, { label: string; cls: string }> = {
  rule: { label: '規則式', cls: 'cat-rule' },
  score: { label: '臨床評分', cls: 'cat-score' },
  ml: { label: '機器學習', cls: 'cat-ml' },
  dl: { label: '深度學習', cls: 'cat-dl' },
  custom_rule: { label: '自訂規則', cls: 'cat-custom' },
  custom_model: { label: '自訂 AI 模型', cls: 'cat-model' },
  plugin: { label: 'Python 外掛', cls: 'cat-plugin' },
}

export const sexLabel = (s: string): string => (s === 'M' ? '男' : '女')
export const locationLabel = (l: string): string => (l === 'OR' ? '手術室' : '恢復室')
export const pct = (v: number | null | undefined): string => (v == null ? '—' : `${Math.round(v * 100)}%`)
