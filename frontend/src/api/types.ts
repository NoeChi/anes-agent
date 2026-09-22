/* 後端 API 與 WebSocket 的資料型別（對應 backend/app/main.py） */

export type Severity = 'info' | 'warning' | 'critical'
export type PatientStatus = Severity | 'normal' | 'unchecked'
export type Location = 'OR' | 'PACU'
export type Phase = 'induction' | 'maintenance' | 'emergence' | 'pacu'
export type Category = 'rule' | 'score' | 'ml' | 'dl' | 'custom_rule' | 'custom_model' | 'plugin'
export type Num = number | null

export interface Vitals {
  hr: Num
  sbp: Num
  dbp: Num
  map: Num
  spo2: Num
  etco2: Num
  rr: Num
  temp: Num
  bis: Num
  ppeak: Num
  pain: Num
}

export interface PatientCore {
  pid: string
  bed: string
  name: string
  age: number
  sex: 'M' | 'F'
  asa: number
  surgery: string
  anes_label: string
  anes_class: string
  location: Location
  phase: Phase
  phase_label: string
  minutes: number
  vitals: Vitals
  rhythm: string
  ebl: number
  uo: Num
  ponv: boolean
}

export interface PatientBrief extends PatientCore {
  status: PatientStatus
  alert_titles: string[]
  acknowledged: boolean
}

export interface Schedule {
  enabled: boolean
  mode: 'interval' | 'schedule'
  next_due: Num
  seconds_to_next: Num
  last_round: Num
  busy: boolean
}

export interface LogEntry {
  t: number
  pid: string | null
  text: string
  level: string
}

export interface TickData {
  sim_time: number
  running: boolean
  speed: number
  patients: PatientBrief[]
  schedule: Schedule
  log: LogEntry[]
  pending_actions: number
  active_alerts: number
}

export interface RoundsSettings {
  enabled: boolean
  mode: 'interval' | 'schedule'
  interval_minutes: number
  times: string[]
  window_enabled: boolean
  window_start: string
  window_end: string
  scope: 'all' | 'OR' | 'PACU'
  ai_summary: 'off' | 'when_findings' | 'always'
  critical_recheck_minutes: number
}

export interface SimulationSettings {
  speed: number
  event_rate: number
  running: boolean
}

export interface ModelChoice {
  id: string
  label: string
}

export interface ProviderInfo {
  id: string
  label: string
  env: string
  key_placeholder: string
  console: string
  key_set: boolean
}

export interface LlmSettingsPublic {
  provider: string
  model: string
  openai_model?: string
  effort: 'low' | 'medium' | 'high'
  api_key_set: boolean
  api_key_source: string | null
  api_key_hint: string
  model_choices: ModelChoice[]
  providers: ProviderInfo[]
}

export interface PublicSettings {
  llm: LlmSettingsPublic
  rounds: RoundsSettings
  simulation: SimulationSettings
  tools?: { disabled: string[]; params: Record<string, Record<string, unknown>> }
}

export interface LlmStatus {
  available: boolean
  source?: string | null
  provider?: string
  provider_label?: string
  model?: string
  effort?: string
  last_error?: string | null
}

export interface MlStatus {
  state: string
  progress: number
  message: string
  dataset_ready?: boolean
}

export interface DbStatus {
  ok: boolean
  backend: string
  tables: Record<string, number>
}

export interface AppStateResponse {
  settings: PublicSettings
  llm: LlmStatus
  ml: MlStatus
  schedule: Schedule
  sim: SimulationSettings & { time: number; or: number; pacu: number }
  counts: { patients: number; tools: number; skills: number }
  db?: DbStatus | null
}

export interface Finding {
  severity: Severity
  severity_label: string
  title: string
  detail: string
  suggestion: string
  evidence?: Record<string, unknown>
  tool_id: string
  tool_name: string
  new?: boolean
  alert_id?: string
  acknowledged?: boolean
}

export interface ToolResult {
  tool_id: string
  tool_name: string
  patient_id: string
  ok: boolean
  applicable: boolean
  summary: string
  findings: Finding[]
  values: Record<string, unknown>
  error: string | null
  enabled?: boolean
  category?: string
}

export interface Labs {
  t: number
  reason: string
  ph: number
  paco2: number
  pao2: number
  hco3: number
  be: number
  hb: number
  k: number
  na: number
  glucose: number
  lactate: number
  ica: number
}

export interface Intervention {
  t: number
  type: string
  label: string
  by: string
}

export interface Note {
  t: number
  text: string
  by: string
}

export interface Alert {
  id: string
  key?: string
  pid: string
  bed: string
  tool_id: string
  tool_name: string
  severity: Severity
  severity_label: string
  title: string
  detail: string
  suggestion: string
  first_seen: number
  last_seen: number
  status: 'active' | 'resolved'
  acknowledged: boolean
  resolved_at: Num
  rounds_seen: number
}

export interface PatientStatusInfo {
  severity: PatientStatus
  critical: number
  warning: number
  info: number
  titles: string[]
  round_id: string
  checked_at: number
}

export interface PatientDetail extends PatientCore {
  mrn: string
  height_cm: number
  weight_kg: number
  bmi: number
  comorbidities: string[]
  allergies: string[]
  smoker: boolean
  ponv_history: boolean
  specialty: string
  planned_min: number
  case_minutes: number
  airway: string
  baseline: { hr: number; sbp: number; dbp: number; spo2: number; rr: number; temp: number }
  drugs: string[]
  fluids: { crystalloid_ml: number; blood_ml: number; ebl_ml: number; ebl_pct: number; urine_ml: Num }
  labs: Labs | null
  lab_history: Labs[]
  interventions: Intervention[]
  notes: Note[]
  sim_time: number
  status: PatientStatusInfo | null
  alerts: Alert[]
}

export type TrendField = 'hr' | 'sbp' | 'dbp' | 'map' | 'spo2' | 'etco2' | 'rr' | 'temp' | 'bis' | 'pain'
export type Trend = { t: number[] } & Partial<Record<TrendField, Num[]>>

export interface ParamSpec {
  key: string
  label: string
  default: number | string | boolean
  type: string
  unit: string
  min: Num
  max: Num
  step: Num
}

export interface ModelMetrics {
  auc?: Num
  threshold?: number
  suggested_threshold?: number
  sensitivity?: Num
  specificity?: Num
  ppv?: Num
  n_train?: number
  n_test?: number
  patients_train?: number
  patients_test?: number
  prevalence?: number
  train_seconds?: number
  importance?: { feature: string; label: string; weight: number }[]
  note?: string
}

export interface ModelMeta {
  id: string
  name: string
  kind: string
  family?: string
  algorithm?: string
  algorithm_label?: string
  target?: string
  target_label?: string
  features: string[]
  threshold: number
  critical_threshold?: number
  metrics: ModelMetrics
  description?: string
  trained_at?: string
  source?: string
  locations?: Location[]
  input_desc?: string
}

export interface RuleCondition {
  field: string
  op: string
  value?: number | string | null
  duration_min?: number
  window_min?: number
}

export interface RuleSpec {
  id?: string
  name: string
  description: string
  severity: Severity
  logic: 'all' | 'any'
  conditions: RuleCondition[]
  locations: Location[]
  message: string
  suggestion: string
  author?: string
  updated_at?: string
}

export interface ToolInfo {
  id: string
  name: string
  category: Category
  category_label: string
  description: string
  how_it_works: string
  locations: Location[]
  params: ParamSpec[]
  builtin: boolean
  enabled: boolean
  param_values: Record<string, number | string | boolean>
  model?: ModelMeta
  spec?: RuleSpec
}

export type RuleFieldType = 'number' | 'bool' | 'select' | 'text'

export interface RuleField {
  key: string
  label: string
  unit: string
  type: RuleFieldType
  group: string
  history: boolean
  options: [string, string][] | null
}

export interface RuleCatalog {
  fields: RuleField[]
  operators: Record<RuleFieldType, [string, string][]>
}

export interface RuleTestResult {
  matches: { pid: string; bed: string; label: string; values: string[] }[]
  checked: number
  logic_text: string
}

export interface MlTarget {
  id: string
  label: string
  short: string
  default_features: string[]
}

export interface MlAlgorithm {
  id: string
  label: string
  family: string
  desc: string
}

export interface MlFeature {
  key: string
  label: string
  group: string
}

export interface MlCatalog {
  targets: MlTarget[]
  algorithms: MlAlgorithm[]
  features: MlFeature[]
  status: MlStatus
}

export interface Skill {
  id: string
  name: string
  description: string
  enabled: boolean
  triggers: { tools: string[]; keywords: string[]; always: boolean }
  use_in: ('rounds' | 'chat')[]
  author: string
  updated_at: string
  body: string
}

export interface RoundBrief {
  id: string
  trigger: string
  trigger_label: string
  scope: string
  wall_time: number
  sim_time: number
  duration_ms: number
  patients_checked: number
  tools_run: number
  n_critical: number
  n_warning: number
  n_info: number
  new_alerts: number
  resolved_alerts: number
  summary_source: 'template' | 'ai'
  summary_status: 'done' | 'pending' | 'failed'
}

export interface RoundPatient {
  pid: string
  bed: string
  label: string
  severity: PatientStatus
  findings: Finding[]
  skills: { id: string; name: string }[]
  new_count: number
  tool_errors: string[]
}

export interface RoundReport extends RoundBrief {
  resolved: { bed: string; pid: string; title: string }[]
  patients: RoundPatient[]
  summary_md: string
  summary_error: string | null
  summary_model?: string
}

export interface RoundSummaryEvent extends RoundBrief {
  summary_md: string
  summary_error: string | null
}

export interface PendingAction {
  id: string
  pid: string
  bed: string
  intervention: string
  label: string
  reason: string
  source: string
  session_id: string | null
  status: 'pending' | 'confirmed' | 'rejected' | 'failed'
  created_at: number
  resolved_at: Num
  result: string | null
}

export interface ChatStep {
  id?: string
  tool: string
  label: string
  status: 'running' | 'done' | 'error'
  error?: string
}

export interface ChatStepEvent extends ChatStep {
  session_id: string
}

export interface ChatDisplayMessage {
  role: 'user' | 'assistant'
  text: string
  steps?: ChatStep[]
  mode?: string
  error?: string | null
  t: number
}

export interface ChatResponse {
  reply: string
  steps: ChatStep[]
  mode: string
  error?: string | null
  session_id: string
  model?: string
}

export interface InterventionOption {
  id: string
  label: string
}

export interface EventCatalogItem {
  id: string
  label: string
  desc: string
  locations: Location[]
  treatments: { id: string; label: string; efficacy: number }[]
}

export interface ActiveEvent {
  pid: string
  bed: string
  type: string
  label: string
  level: number
  minutes: number
  ending: boolean
  treatments: string[]
}

export interface SimEventsResponse {
  catalog: EventCatalogItem[]
  active: ActiveEvent[]
  log: LogEntry[]
}

export interface WsEventMap {
  hello: { settings: PublicSettings; llm: LlmStatus; ml: MlStatus }
  tick: TickData
  round_started: { id: string; trigger: string; count: number; label: string }
  round_completed: RoundBrief
  round_summary: RoundSummaryEvent
  alert: Alert
  chat_step: ChatStepEvent
  pending_action: PendingAction
  action_resolved: PendingAction
  settings_changed: PublicSettings
  tools_changed: { id?: string }
  skills_changed: { id?: string }
  ml_status: MlStatus
  alerts_changed: { id?: string; pid?: string }
  sim_reset: Record<string, never>
}
