/* 全站共用的病人詳細視窗 */
import { ref } from 'vue'

export const openPatientId = ref<string | null>(null)

export function openPatient(pid: string): void {
  openPatientId.value = pid
}

export function closePatient(): void {
  openPatientId.value = null
}
