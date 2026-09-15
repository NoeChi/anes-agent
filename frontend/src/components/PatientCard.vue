<script setup lang="ts">
import { computed } from 'vue'
import type { PatientBrief } from '@/api/types'
import { sevOf, sexLabel } from '@/utils/format'
import { vitalFlag } from '@/utils/vitals'

const props = defineProps<{ patient: PatientBrief }>()
const sev = computed(() => sevOf(props.patient.status))
const v = computed(() => props.patient.vitals)
const titles = computed(() => (props.patient.alert_titles ?? []).slice(0, 2))
const flag = (key: string, value: number | null) => vitalFlag(key, value, props.patient)
</script>

<template>
  <!-- 子元素 pointer-events: none（見 style.css），點擊一律落在卡片本身 -->
  <div class="pcard" :class="`sev-${sev.cls}`">
    <div class="pc-top">
      <span class="bed">{{ patient.bed }}</span>
      <span class="pid">{{ patient.pid }}</span>
      <span class="sev-dot" :class="sev.cls" :title="sev.label" />
    </div>
    <div class="pc-sub" :title="patient.surgery">{{ patient.age }}{{ sexLabel(patient.sex) }}・{{ patient.surgery }}</div>
    <div class="pc-phase">
      <span class="badge" :class="`phase-${patient.phase}`">{{ patient.phase_label }}</span>
      <span class="muted">{{ patient.minutes }} 分</span>
      <span v-if="patient.ponv" class="badge badge-warn">噁心</span>
    </div>
    <div class="pc-vitals">
      <div class="v" :class="flag('hr', v.hr)"><span>HR</span><b>{{ v.hr ?? '—' }}</b></div>
      <div class="v wide" :class="flag('map', v.map)">
        <span>血壓（MAP）</span><b>{{ v.sbp ?? '—' }}/{{ v.dbp ?? '—' }}<i>({{ v.map ?? '—' }})</i></b>
      </div>
      <div class="v" :class="flag('spo2', v.spo2)"><span>SpO₂</span><b>{{ v.spo2 ?? '—' }}</b></div>
      <div class="v" :class="flag('etco2', v.etco2)"><span>EtCO₂</span><b>{{ v.etco2 ?? '—' }}</b></div>
      <div v-if="patient.location === 'PACU'" class="v" :class="flag('pain', v.pain)"><span>疼痛</span><b>{{ v.pain ?? '—' }}</b></div>
      <div v-else class="v" :class="flag('bis', v.bis)"><span>BIS</span><b>{{ v.bis ?? '—' }}</b></div>
      <div class="v" :class="flag('temp', v.temp)"><span>體溫</span><b>{{ v.temp ?? '—' }}</b></div>
    </div>
    <div class="pc-alerts">
      <span v-for="t in titles" :key="t" :class="sev.cls">{{ t }}</span>
      <span v-if="patient.acknowledged && titles.length" class="ack">✓ 已確認</span>
    </div>
  </div>
</template>
