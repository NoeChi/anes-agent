/* 即時狀態：由 WebSocket tick 與 /api/state 更新 */
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { AppStateResponse, DbStatus, LlmStatus, LogEntry, MlStatus, PatientBrief, PublicSettings, Schedule, TickData } from '@/api/types'

const logKeys = new Set<string>()

export const useLiveStore = defineStore('live', {
  state: () => ({
    patients: [] as PatientBrief[],
    simTime: 0,
    schedule: null as Schedule | null,
    settings: null as PublicSettings | null,
    llm: null as LlmStatus | null,
    ml: null as MlStatus | null,
    db: null as DbStatus | null,
    activeAlerts: 0,
    pendingActions: 0,
    logs: [] as LogEntry[],
  }),
  actions: {
    applyTick(d: TickData) {
      this.patients = d.patients
      this.simTime = d.sim_time
      this.schedule = d.schedule
      this.activeAlerts = d.active_alerts
      this.pendingActions = d.pending_actions
      if (this.settings) {
        this.settings.simulation.running = d.running
        this.settings.simulation.speed = d.speed
      }
      if (d.log?.length) this.addLogs(d.log)
    },
    addLogs(items: LogEntry[]) {
      const fresh: LogEntry[] = []
      for (const e of items) {
        const key = `${e.t}|${e.text}`
        if (logKeys.has(key)) continue
        logKeys.add(key)
        fresh.push(e)
      }
      if (!fresh.length) return
      this.logs = [...fresh.reverse(), ...this.logs].slice(0, 80)
    },
    clearLogs() {
      logKeys.clear()
      this.logs = []
    },
    applySettings(s: PublicSettings) {
      this.settings = s
      this.llm = { ...(this.llm ?? {}), available: s.llm.api_key_set, model: s.llm.model, effort: s.llm.effort }
    },
    async refreshState(): Promise<AppStateResponse> {
      const s = await api.get<AppStateResponse>('/api/state')
      this.settings = s.settings
      this.llm = s.llm
      this.ml = s.ml
      this.schedule = s.schedule
      this.db = s.db ?? null
      return s
    },
    async loadPatients() {
      this.patients = await api.get<PatientBrief[]>('/api/patients')
    },
  },
})
