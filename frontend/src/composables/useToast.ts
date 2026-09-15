import { ref } from 'vue'

export type ToastType = 'info' | 'ok' | 'warn' | 'crit' | 'error'

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface ToastItem {
  id: number
  message: string
  type: ToastType
  action?: ToastAction
}

export const toasts = ref<ToastItem[]>([])
let seq = 0

export function dismissToast(id: number): void {
  toasts.value = toasts.value.filter((t) => t.id !== id)
}

export function toast(message: string, type: ToastType = 'info', opts: { action?: ToastAction; timeout?: number } = {}): void {
  const id = ++seq
  const item: ToastItem = { id, message, type }
  if (opts.action) item.action = opts.action
  toasts.value.push(item)
  while (toasts.value.length > 5) toasts.value.shift()
  const timeout = opts.timeout ?? (type === 'crit' || type === 'error' ? 10000 : 4500)
  if (timeout) setTimeout(() => dismissToast(id), timeout)
}
