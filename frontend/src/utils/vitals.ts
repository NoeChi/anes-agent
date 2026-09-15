/* 生命徵象異常標示（畫面提示用，正式判讀以工具為準） */
import type { PatientCore } from '@/api/types'

export type VitalFlag = '' | 'warn' | 'bad'
type Ctx = Pick<PatientCore, 'location' | 'anes_class' | 'phase'>

export function vitalFlag(key: string, v: number | null | undefined, p?: Ctx): VitalFlag {
  if (v == null) return ''
  const gaMaint = !!p && p.location === 'OR' && p.anes_class === 'GA' && p.phase === 'maintenance'
  switch (key) {
    case 'map':
      return v < 55 ? 'bad' : v < 65 || v > 120 ? 'warn' : ''
    case 'hr':
      return v < 40 || v > 140 ? 'bad' : v < 50 || v > 120 ? 'warn' : ''
    case 'spo2':
      return v < 88 ? 'bad' : v < 92 ? 'warn' : ''
    case 'etco2':
      return v > 60 ? 'bad' : v > 50 || (gaMaint && v < 25) ? 'warn' : ''
    case 'temp':
      return v < 35 || v > 39.5 ? 'bad' : v < 36 || v > 38.5 ? 'warn' : ''
    case 'bis':
      return gaMaint && (v > 60 || v < 35) ? 'warn' : ''
    case 'pain':
      return v >= 7 ? 'warn' : ''
    case 'rr':
      return v < 8 ? 'bad' : v > 30 ? 'warn' : ''
    default:
      return ''
  }
}
