/* 確認對話框（取代瀏覽器 confirm） */
import { shallowRef } from 'vue'

export interface ConfirmRequest {
  title: string
  message: string
  okLabel: string
  danger: boolean
  resolve: (ok: boolean) => void
}

export const confirmRequest = shallowRef<ConfirmRequest | null>(null)

export function confirmDialog(title: string, message: string, okLabel = '確定', danger = false): Promise<boolean> {
  return new Promise((resolve) => {
    confirmRequest.value?.resolve(false)
    confirmRequest.value = { title, message, okLabel, danger, resolve }
  })
}

export function answerConfirm(ok: boolean): void {
  const req = confirmRequest.value
  confirmRequest.value = null
  req?.resolve(ok)
}
