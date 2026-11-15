export interface Session {
  token: string
  name: string
  role: 'CUSTOMER' | 'OPERATOR'
  expiresAt: number
}

export interface Zone {
  zone_id: string
  name: string
  zone_type: string
}

export interface Report {
  report_id: string
  status: string
  service?: string
  problem_type?: string
  service_number?: string
  zone_id?: string
  location_text?: string
  description?: string
  occurred_at?: string
  created_at?: string
  updated_at?: string
  incident_id?: string
  history?: ReportHistory[]
}

export interface ReportHistory {
  from_status?: string | null
  to_status: string
  actor?: string
  reason?: string
  at: string
}

export interface Incident {
  incident_id: string
  zone_id: string
  service: string
  status: string
  opened_at?: string
  updated_at?: string
}

export interface IncidentHistory {
  from_status?: string | null
  to_status?: string
  change?: string
  actor?: string
  reason?: string
  at?: string
}

export interface AntennaLink {
  antenna_id?: string
  episode_id?: string
  state?: string
  linked_at?: string
  recovered_at?: string
}

export interface OperatorIncident extends Incident {
  priority?: string
  affected_users?: number
  report_count?: number
  detected_by?: string
  origin?: string
  worst_antenna_state?: string
  tech_recovered?: boolean
  review_required?: boolean
  evidence_tech?: unknown
  evidence_users?: unknown
  history?: IncidentHistory[]
  links?: { reports?: number; users?: number; antennas?: AntennaLink[] }
}

export interface Trends {
  days: number
  top_zonas: { zone_id: string; name: string; reports: number; incidents: number }[]
  top_antenas: { antenna_id: string; zone_id: string; episodes: number }[]
  top_tipos: { problem_type: string; count: number }[]
  recurrentes: { antenna_id: string; zone_id: string; episodes_7d: number }[]
  deteccion: { avg_lag_seconds: number; detected_by_users: number; detected_by_antenna: number }
}

export interface Suggestion {
  available: boolean
  hypotheses?: { title: string; rationale: string }[]
  model?: string
  generated_at?: string
}

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

export interface CreateReportBody {
  service_number: string
  zone_id: string
  service: 'MOVIL' | 'INTERNET'
  problem_type: string
  description: string
  location_text: string
  occurred_at: string
}
