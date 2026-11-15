import type { CreateReportBody, Incident, OperatorIncident, Page, Report, Suggestion, Trends, Zone } from './types'

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'https://ynyvt8x51k.execute-api.us-east-1.amazonaws.com').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number | null,
    public code: string | null,
    public path: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH'
  token?: string
  body?: unknown
  idempotencyKey?: string
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.token) headers.Authorization = `Bearer ${options.token}`
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: AbortSignal.timeout(15000),
    })
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === 'TimeoutError'
    throw new ApiError(
      timedOut ? 'El servidor tardó demasiado en responder.' : 'No se pudo conectar con el servicio. Comprueba la red o CORS.',
      null,
      timedOut ? 'TIMEOUT' : 'NETWORK',
      path,
    )
  }

  const raw = await response.text()
  let payload: unknown
  try {
    payload = raw ? JSON.parse(raw) : null
  } catch {
    throw new ApiError('El servidor devolvió una respuesta que no es JSON.', response.status, 'INVALID_RESPONSE', path)
  }

  if (!response.ok) {
    const body = payload as { error?: { code?: string; message?: string } } | null
    throw new ApiError(body?.error?.message || `El servicio respondió HTTP ${response.status}.`, response.status, body?.error?.code || null, path)
  }
  if (payload === null || typeof payload !== 'object') {
    throw new ApiError('El servidor no devolvió los datos esperados.', response.status, 'INVALID_RESPONSE', path)
  }
  return payload as T
}

export interface LoginResponse {
  token: string
  expires_in: number
  role: 'CUSTOMER' | 'OPERATOR'
  name: string
}

export const api = {
  login: (identifier: string, password: string) =>
    request<LoginResponse>('/auth/login', { method: 'POST', body: { identifier, password } }),
  zones: (token: string) => request<{ items: Zone[] }>('/zonas', { token }),
  reports: (token: string, cursor?: string) => {
    const query = new URLSearchParams({ limit: '12' })
    if (cursor) query.set('cursor', cursor)
    return request<Page<Report>>(`/reportes?${query}`, { token })
  },
  report: (token: string, id: string) => request<Report>(`/reportes/${encodeURIComponent(id)}`, { token }),
  createReport: (token: string, body: CreateReportBody, idempotencyKey: string) =>
    request<Report>('/reportes', { method: 'POST', token, body, idempotencyKey }),
  incidents: (token: string, zoneId: string, cursor?: string) => {
    const query = new URLSearchParams({ zone_id: zoneId, limit: '20' })
    if (cursor) query.set('cursor', cursor)
    return request<Page<Incident>>(`/incidentes?${query}`, { token })
  },
}

export const operatorApi = {
  incidents: (token: string, status: string, zoneId?: string, cursor?: string) => {
    const query = new URLSearchParams({ status, limit: '20' })
    if (zoneId) query.set('zone_id', zoneId)
    if (cursor) query.set('cursor', cursor)
    return request<Page<OperatorIncident>>(`/incidentes?${query}`, { token })
  },
  incident: (token: string, id: string) => request<OperatorIncident>(`/incidentes/${encodeURIComponent(id)}`, { token }),
  updateIncident: (token: string, id: string, toStatus: string, reason: string) =>
    request<OperatorIncident>(`/incidentes/${encodeURIComponent(id)}/estado`, {
      method: 'PATCH', token, body: { to_status: toStatus, reason },
    }),
  reports: (token: string, zoneId: string, cursor?: string) => {
    const query = new URLSearchParams({ zone_id: zoneId, limit: '20' })
    if (cursor) query.set('cursor', cursor)
    return request<Page<Report>>(`/reportes?${query}`, { token })
  },
  report: (token: string, id: string) => request<Report>(`/reportes/${encodeURIComponent(id)}`, { token }),
  updateReport: (token: string, id: string, toStatus: string, reason: string) =>
    request<Report>(`/reportes/${encodeURIComponent(id)}/estado`, {
      method: 'PATCH', token, body: { to_status: toStatus, reason },
    }),
  trends: (token: string, days: 7 | 30) => request<Trends>(`/tendencias?days=${days}`, { token }),
  suggestion: (token: string, id: string) => request<Suggestion>(`/incidentes/${encodeURIComponent(id)}/sugerencia`, { token }),
}

export function readableError(error: unknown): { message: string; detail: string } {
  if (!(error instanceof ApiError)) return { message: 'Ocurrió un error inesperado.', detail: 'Vuelve a intentarlo.' }
  if (error.code === 'ROLE') return { message: error.message, detail: 'Comprueba que tu cuenta tenga acceso a esta sección.' }
  if (error.status === 401 && error.path === '/auth/login') return { message: 'Identificación o contraseña incorrectas.', detail: 'Revisa tus datos e inténtalo de nuevo.' }
  if (error.status === 401) return { message: 'Tu sesión venció o no es válida.', detail: 'Inicia sesión de nuevo.' }
  if (error.status === 403) return { message: 'No tienes permiso para consultar estos datos.', detail: `${error.path} · HTTP 403` }
  if (error.status === 404) return { message: 'No se encontró el recurso o la ruta solicitada.', detail: `${error.path} · HTTP 404` }
  if (error.status === 501) return { message: 'Esta función todavía no está disponible en el backend.', detail: `${error.path} · HTTP 501` }
  if (error.status && error.status >= 500) return { message: 'El backend no pudo completar esta operación.', detail: `${error.path} · HTTP ${error.status}${error.code ? ` · ${error.code}` : ''}` }
  return { message: error.message, detail: `${error.path} · ${error.status ? `HTTP ${error.status}` : error.code || 'sin respuesta'}` }
}
