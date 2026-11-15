export interface Session {
  token: string
  name: string
  role: 'CUSTOMER'
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
