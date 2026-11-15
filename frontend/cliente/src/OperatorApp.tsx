import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  Activity, ArrowLeft, ArrowRight, ArrowUpRight, Bell, ChartNoAxesCombined,
  Check, ChevronRight, CircleAlert, Clock3, FileText, LayoutDashboard,
  Lightbulb, LoaderCircle, LogOut, MapPin, Menu, RadioTower, RefreshCw,
  Search, ShieldCheck, Signal, Users, X,
} from 'lucide-react'
import { ApiError, api, operatorApi, readableError } from './api'
import type { OperatorIncident, Page, Report, Session, Suggestion, Trends, Zone } from './types'
import './operator.css'

type View = 'queue' | 'incident' | 'reports' | 'report' | 'trends'
type LoadState = 'idle' | 'loading' | 'ready' | 'error'
type IncidentStatus = 'EVALUACION' | 'CONFIRMADO' | 'RESTABLECIDO' | 'CERRADO'

const AZURE_STATUS_URL = (import.meta.env.VITE_AZURE_STATUS_URL || 'https://mango-ground-073e60210.3.azurestaticapps.net').replace(/\/$/, '')
const INCIDENT_STATUSES: IncidentStatus[] = ['EVALUACION', 'CONFIRMADO', 'RESTABLECIDO', 'CERRADO']
const INCIDENT_NEXT: Record<IncidentStatus, string[]> = {
  EVALUACION: ['CONFIRMADO', 'CERRADO'],
  CONFIRMADO: ['RESTABLECIDO'],
  RESTABLECIDO: ['CERRADO', 'CONFIRMADO'],
  CERRADO: [],
}
const REPORT_NEXT: Record<string, string[]> = {
  REGISTRADA: ['EN_REVISION'],
  EN_REVISION: ['EN_ATENCION'],
  EN_ATENCION: ['SOLUCIONADA'],
  SOLUCIONADA: ['CERRADA', 'EN_ATENCION'],
  CERRADA: [],
}
const LABEL: Record<string, string> = {
  EVALUACION: 'En evaluación', CONFIRMADO: 'Confirmado', RESTABLECIDO: 'Restablecido',
  CERRADO: 'Cerrado', REGISTRADA: 'Registrada', EN_REVISION: 'En revisión',
  EN_ATENCION: 'En atención', SOLUCIONADA: 'Solucionada', CERRADA: 'Cerrada',
  USUARIOS: 'Reportes de usuarios', ANTENA: 'Señal de antena',
  MOVIL: 'Telefonía móvil', INTERNET: 'Internet', ANY: 'Todos los servicios',
  SIN_SENAL: 'Sin señal', SIN_INTERNET: 'Sin internet', LLAMADAS: 'Llamadas',
  SMS: 'Mensajes', LENTITUD: 'Lentitud', OTRO: 'Otro',
  INHABILITADA: 'Inhabilitada', CAIDA: 'Caída', SATURADA: 'Saturada', NORMAL: 'Normal',
  CREATED: 'Creado', EVIDENCE: 'Evidencia añadida', RECOVERY: 'Recuperación técnica',
}

function label(value?: string | null) { return value ? LABEL[value] || value.replaceAll('_', ' ') : 'No disponible' }
function shortId(value: string) { return value.slice(0, 8) }
function dateLabel(value?: string) {
  if (!value) return 'Sin fecha'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'Fecha no disponible' : parsed.toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })
}
function number(value?: number) { return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('es-PE') : '—' }

function Status({ value }: { value: string }) {
  const tone = ['CERRADO', 'CERRADA', 'RESTABLECIDO', 'SOLUCIONADA'].includes(value) ? 'done'
    : ['EVALUACION', 'REGISTRADA'].includes(value) ? 'pending' : 'active'
  return <span className={`op-status ${tone}`}><span />{label(value)}</span>
}
function Priority({ value }: { value?: string }) {
  return <span className={`op-priority ${value === 'P1' ? 'p1' : value === 'P2' ? 'p2' : 'p3'}`}>{value || 'Sin prioridad'}</span>
}
function ErrorBlock({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { message, detail } = readableError(error)
  return <div className="op-error" role="alert"><CircleAlert size={19} /><div><strong>{message}</strong><p>{detail}</p>{onRetry && <button className="op-link" type="button" onClick={onRetry}>Volver a intentar <ArrowRight size={15} /></button>}</div></div>
}
function Loading({ text = 'Consultando el servicio…' }: { text?: string }) {
  return <div className="op-loading" role="status"><LoaderCircle className="spin" size={20} />{text}</div>
}
function Empty({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return <div className="op-empty"><span className="op-empty-icon">{icon}</span><h3>{title}</h3><p>{text}</p></div>
}
function Field({ title, value }: { title: string; value: ReactNode }) {
  return <div className="op-field"><span>{title}</span><strong>{value}</strong></div>
}

function TransitionForm({ entityId, current, options, busy, error, success, onApply }: {
  entityId: string; current: string; options: string[]; busy: boolean; error: unknown; success: string;
  onApply: (target: string, reason: string) => Promise<void>
}) {
  const [target, setTarget] = useState('')
  const [reason, setReason] = useState('')
  const [reviewing, setReviewing] = useState(false)
  useEffect(() => { setTarget(''); setReason(''); setReviewing(false) }, [entityId, current])

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!target || reason.trim().length < 3) return
    if (!reviewing) { setReviewing(true); return }
    void onApply(target, reason.trim())
  }

  return <section className="op-card op-transition"><div className="op-card-title"><div><span className="op-kicker">DECISIÓN OPERATIVA</span><h2>Cambiar estado</h2></div><ShieldCheck size={22} /></div>
    {options.length === 0 ? <p className="op-muted">Este caso está cerrado y no admite más transiciones.</p> : <form onSubmit={submit}>
      <label htmlFor="next-status">Siguiente estado permitido</label><select id="next-status" value={target} onChange={event => { setTarget(event.target.value); setReviewing(false) }} required><option value="">Selecciona una acción</option>{options.map(option => <option key={option} value={option}>{label(option)}</option>)}</select>
      <label htmlFor="status-reason">Motivo para el historial</label><textarea id="status-reason" value={reason} onChange={event => { setReason(event.target.value); setReviewing(false) }} minLength={3} maxLength={500} rows={3} placeholder="Describe la evidencia o decisión tomada" required />
      {reviewing && <div className="op-review"><strong>Revisa antes de guardar</strong><span>{label(current)} → {label(target)}</span><p>{reason.trim()}</p></div>}
      {error != null && <ErrorBlock error={error} />}
      {success && <div className="op-success" role="status"><Check size={17} />{success}</div>}
      <div className="op-action-buttons">{reviewing && <button className="op-button subtle" type="button" onClick={() => setReviewing(false)}>Volver</button>}<button className="op-button primary" type="submit" disabled={busy || !target || reason.trim().length < 3}>{busy ? <><LoaderCircle className="spin" size={16} /> Guardando…</> : reviewing ? 'Confirmar cambio' : 'Revisar cambio'} <ArrowRight size={16} /></button></div>
    </form>}
  </section>
}

function Timeline({ entries, fallbackStatus, fallbackAt }: { entries?: { from_status?: string | null; to_status?: string; change?: string; reason?: string; at?: string }[]; fallbackStatus: string; fallbackAt?: string }) {
  const rows = entries?.length ? entries : [{ to_status: fallbackStatus, at: fallbackAt }]
  return <div className="op-timeline">{rows.map((entry, index) => <div className="op-timeline-row" key={`${entry.at || 'initial'}-${index}`}><span className="op-timeline-dot" /><div><strong>{entry.change && entry.change !== 'STATUS' ? `${label(entry.change)} · ${label(entry.to_status)}` : label(entry.to_status)}</strong><small>{dateLabel(entry.at)}</small>{entry.reason && <p>{entry.reason}</p>}</div></div>)}</div>
}

function Bars({ rows }: { rows: { id: string; name: string; count: number; secondary?: string }[] }) {
  const max = Math.max(1, ...rows.map(row => row.count))
  if (!rows.length) return <p className="op-muted">No hay datos para este periodo.</p>
  return <div className="op-bars">{rows.map(row => <div className="op-bar-row" key={row.id}><div><strong>{row.name}</strong><span>{row.secondary}</span></div><div className="op-bar-track"><span style={{ width: `${Math.max(4, row.count / max * 100)}%` }} /></div><b>{number(row.count)}</b></div>)}</div>
}

interface Props { session: Session; onUnauthorized: () => void; onLogout: () => void }

export default function OperatorApp({ session, onUnauthorized, onLogout }: Props) {
  const [view, setView] = useState<View>('queue')
  const [menuOpen, setMenuOpen] = useState(false)
  const [zones, setZones] = useState<Zone[]>([])
  const [zonesState, setZonesState] = useState<LoadState>('idle')
  const [zonesError, setZonesError] = useState<unknown>(null)
  const [queueStatus, setQueueStatus] = useState<IncidentStatus>('EVALUACION')
  const [queueZone, setQueueZone] = useState('')
  const [incidents, setIncidents] = useState<OperatorIncident[]>([])
  const [queueCursor, setQueueCursor] = useState<string | null>(null)
  const [queueState, setQueueState] = useState<LoadState>('idle')
  const [queueError, setQueueError] = useState<unknown>(null)
  const [queueAt, setQueueAt] = useState<string | null>(null)
  const [incidentId, setIncidentId] = useState<string | null>(null)
  const [incident, setIncident] = useState<OperatorIncident | null>(null)
  const [incidentState, setIncidentState] = useState<LoadState>('idle')
  const [incidentError, setIncidentError] = useState<unknown>(null)
  const [incidentActionError, setIncidentActionError] = useState<unknown>(null)
  const [incidentSaved, setIncidentSaved] = useState('')
  const [incidentSaving, setIncidentSaving] = useState(false)
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null)
  const [suggestionState, setSuggestionState] = useState<LoadState>('idle')
  const [suggestionError, setSuggestionError] = useState<unknown>(null)
  const [reportZone, setReportZone] = useState('')
  const [reports, setReports] = useState<Report[]>([])
  const [reportsCursor, setReportsCursor] = useState<string | null>(null)
  const [reportsState, setReportsState] = useState<LoadState>('idle')
  const [reportsError, setReportsError] = useState<unknown>(null)
  const [reportLookup, setReportLookup] = useState('')
  const [reportId, setReportId] = useState<string | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [reportState, setReportState] = useState<LoadState>('idle')
  const [reportError, setReportError] = useState<unknown>(null)
  const [reportActionError, setReportActionError] = useState<unknown>(null)
  const [reportSaved, setReportSaved] = useState('')
  const [reportSaving, setReportSaving] = useState(false)
  const [trendsDays, setTrendsDays] = useState<7 | 30>(7)
  const [trends, setTrends] = useState<Trends | null>(null)
  const [trendsState, setTrendsState] = useState<LoadState>('idle')
  const [trendsError, setTrendsError] = useState<unknown>(null)
  const queueRequest = useRef(0)
  const incidentRequest = useRef(0)
  const reportsRequest = useRef(0)
  const reportRequest = useRef(0)
  const trendsRequest = useRef(0)

  function fail(error: unknown, setError: (value: unknown) => void, setState: (value: LoadState) => void) {
    if (error instanceof ApiError && error.status === 401) onUnauthorized()
    else { setError(error); setState('error') }
  }
  function navigate(next: View) { setView(next); setMenuOpen(false) }

  async function loadZones() {
    setZonesState('loading'); setZonesError(null)
    try {
      const result = await api.zones(session.token)
      if (!Array.isArray(result.items)) throw new ApiError('Catálogo de zonas inválido.', 200, 'INVALID_RESPONSE', '/zonas')
      setZones(result.items)
      setReportZone(old => old || result.items[0]?.zone_id || '')
      setZonesState('ready')
    } catch (error) { fail(error, setZonesError, setZonesState) }
  }
  async function loadQueue(status = queueStatus, zone = queueZone, cursor?: string) {
    const requestId = ++queueRequest.current
    setQueueState('loading'); setQueueError(null)
    if (!cursor) { setIncidents([]); setQueueCursor(null) }
    try {
      const result: Page<OperatorIncident> = await operatorApi.incidents(session.token, status, zone || undefined, cursor)
      if (!Array.isArray(result.items)) throw new ApiError('Cola de incidentes inválida.', 200, 'INVALID_RESPONSE', '/incidentes')
      if (requestId !== queueRequest.current) return
      setIncidents(old => cursor ? [...old, ...result.items] : result.items)
      setQueueCursor(result.next_cursor ?? null)
      setQueueAt(new Date().toISOString())
      setQueueState('ready')
    } catch (error) { if (requestId === queueRequest.current) fail(error, setQueueError, setQueueState) }
  }
  async function loadIncident(id: string) {
    const requestId = ++incidentRequest.current
    setIncidentState('loading'); setIncidentError(null)
    try {
      const result = await operatorApi.incident(session.token, id)
      if (!result.incident_id) throw new ApiError('Detalle de incidente inválido.', 200, 'INVALID_RESPONSE', `/incidentes/${id}`)
      if (requestId !== incidentRequest.current) return
      setIncident(result); setIncidentState('ready')
    } catch (error) { if (requestId === incidentRequest.current) fail(error, setIncidentError, setIncidentState) }
  }
  function openIncident(id: string) {
    setIncidentId(id); setIncident(null); setIncidentSaved(''); setIncidentActionError(null)
    setSuggestion(null); setSuggestionError(null); setSuggestionState('idle')
    navigate('incident'); void loadIncident(id)
  }
  async function applyIncident(target: string, reason: string) {
    if (!incidentId) return
    setIncidentSaving(true); setIncidentActionError(null); setIncidentSaved('')
    try {
      await operatorApi.updateIncident(session.token, incidentId, target, reason)
      setIncidentSaved(`Estado guardado: ${label(target)}. El historial se actualizó.`)
      await loadIncident(incidentId)
      void loadQueue()
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onUnauthorized()
      else {
        setIncidentActionError(error)
        if (error instanceof ApiError && error.status === 409) void loadIncident(incidentId)
      }
    } finally { setIncidentSaving(false) }
  }
  async function loadSuggestion() {
    if (!incidentId) return
    setSuggestionState('loading'); setSuggestionError(null); setSuggestion(null)
    try {
      const result = await operatorApi.suggestion(session.token, incidentId)
      if (typeof result.available !== 'boolean') throw new ApiError('Respuesta de IA inválida.', 200, 'INVALID_RESPONSE', `/incidentes/${incidentId}/sugerencia`)
      setSuggestion(result); setSuggestionState('ready')
    } catch (error) { fail(error, setSuggestionError, setSuggestionState) }
  }
  async function loadReports(zone = reportZone, cursor?: string) {
    if (!zone) return
    const requestId = ++reportsRequest.current
    setReportsState('loading'); setReportsError(null)
    if (!cursor) { setReports([]); setReportsCursor(null) }
    try {
      const result = await operatorApi.reports(session.token, zone, cursor)
      if (!Array.isArray(result.items)) throw new ApiError('Lista de reportes inválida.', 200, 'INVALID_RESPONSE', '/reportes')
      if (requestId !== reportsRequest.current) return
      setReports(old => cursor ? [...old, ...result.items] : result.items)
      setReportsCursor(result.next_cursor ?? null); setReportsState('ready')
    } catch (error) { if (requestId === reportsRequest.current) fail(error, setReportsError, setReportsState) }
  }
  async function loadReport(id: string) {
    const requestId = ++reportRequest.current
    setReportState('loading'); setReportError(null)
    try {
      const result = await operatorApi.report(session.token, id)
      if (!result.report_id) throw new ApiError('Detalle de reporte inválido.', 200, 'INVALID_RESPONSE', `/reportes/${id}`)
      if (requestId !== reportRequest.current) return
      setReport(result); setReportState('ready')
    } catch (error) { if (requestId === reportRequest.current) fail(error, setReportError, setReportState) }
  }
  function openReport(id: string) {
    setReportId(id); setReport(null); setReportSaved(''); setReportActionError(null)
    navigate('report'); void loadReport(id)
  }
  async function applyReport(target: string, reason: string) {
    if (!reportId) return
    setReportSaving(true); setReportActionError(null); setReportSaved('')
    try {
      await operatorApi.updateReport(session.token, reportId, target, reason)
      setReportSaved(`Estado guardado: ${label(target)}. El historial se actualizó.`)
      await loadReport(reportId)
      void loadReports()
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onUnauthorized()
      else {
        setReportActionError(error)
        if (error instanceof ApiError && error.status === 409) void loadReport(reportId)
      }
    } finally { setReportSaving(false) }
  }
  async function loadTrends(days = trendsDays) {
    const requestId = ++trendsRequest.current
    setTrendsState('loading'); setTrendsError(null)
    try {
      const result = await operatorApi.trends(session.token, days)
      if (!Array.isArray(result.top_zonas) || !Array.isArray(result.top_antenas) || !Array.isArray(result.top_tipos)) throw new ApiError('Tendencias inválidas.', 200, 'INVALID_RESPONSE', '/tendencias')
      if (requestId !== trendsRequest.current) return
      setTrends(result); setTrendsState('ready')
    } catch (error) { if (requestId === trendsRequest.current) fail(error, setTrendsError, setTrendsState) }
  }

  useEffect(() => { void loadZones() }, [session.token])
  useEffect(() => { void loadQueue(queueStatus, queueZone) }, [session.token, queueStatus, queueZone])
  useEffect(() => { if (reportZone) void loadReports(reportZone) }, [session.token, reportZone])
  useEffect(() => { if (view === 'trends') void loadTrends(trendsDays) }, [session.token, view, trendsDays])

  const zoneName = (id?: string) => zones.find(zone => zone.zone_id === id)?.name || id || 'Zona no disponible'
  const nav: { id: View; title: string; icon: ReactNode }[] = [
    { id: 'queue', title: 'Bandeja de incidentes', icon: <LayoutDashboard size={19} /> },
    { id: 'reports', title: 'Reportes por zona', icon: <FileText size={19} /> },
    { id: 'trends', title: 'Tendencias', icon: <ChartNoAxesCombined size={19} /> },
  ]
  const pageName = view === 'incident' ? 'Detalle del incidente' : view === 'report' ? 'Detalle del reporte' : nav.find(item => item.id === view)?.title

  return <div className="operator-shell">
    {menuOpen && <button className="op-overlay" aria-label="Cerrar menú" onClick={() => setMenuOpen(false)} />}
    <aside className={`op-sidebar ${menuOpen ? 'open' : ''}`}>
      <div className="op-brand"><div className="op-brand-mark"><Signal size={22} strokeWidth={2.8} /></div><div><strong>red<span>telecorp</span></strong><small>CENTRO DE OPERACIONES</small></div><button className="op-mobile-close" aria-label="Cerrar menú" onClick={() => setMenuOpen(false)}><X size={19} /></button></div>
      <div className="op-side-label">GESTIÓN DE RED</div><nav aria-label="Navegación de operaciones">{nav.map(item => <button key={item.id} className={`op-nav-item ${view === item.id || (view === 'incident' && item.id === 'queue') || (view === 'report' && item.id === 'reports') ? 'active' : ''}`} onClick={() => navigate(item.id)}>{item.icon}{item.title}</button>)}</nav>
      <div className="op-sidebar-bottom"><div className="op-side-card"><RadioTower size={22} /><strong>Información pública</strong><p>Azure muestra el último estado publicado por zona; comprueba siempre la hora de sincronización.</p><a href={AZURE_STATUS_URL} target="_blank" rel="noopener noreferrer">Abrir estado público <ArrowUpRight size={15} /></a></div><span>Acceso restringido · Operaciones</span></div>
    </aside>
    <div className="op-main"><header className="op-topbar"><div><button className="op-menu" aria-label="Abrir menú" onClick={() => setMenuOpen(true)}><Menu size={22} /></button><span>Centro de operaciones</span><ChevronRight size={15} /><strong>{pageName}</strong></div><div className="op-top-user"><span className="op-live"><span /> Operador</span><span className="op-avatar">{session.name.slice(0, 1).toUpperCase()}</span><b>{session.name}</b><button title="Cerrar sesión" aria-label="Cerrar sesión" onClick={onLogout}><LogOut size={19} /></button></div></header>
      <main className="op-content">
        {view === 'queue' && <>
          <div className="op-heading"><div><span className="op-kicker">PANORAMA OPERATIVO</span><h1>Bandeja de incidentes</h1><p>Revisa las señales y toma decisiones con el historial a la vista.</p></div><button className="op-button outline" onClick={() => void loadQueue()} disabled={queueState === 'loading'}><RefreshCw size={16} /> Actualizar</button></div>
          <div className="op-summary-grid"><div className="op-summary"><span><Activity size={19} /></span><div><small>Casos cargados</small><strong>{queueState === 'ready' ? number(incidents.length) : '—'}</strong><em>Solo páginas consultadas</em></div></div><div className="op-summary"><span className="red"><Bell size={19} /></span><div><small>Prioridad P1 visible</small><strong>{queueState === 'ready' ? number(incidents.filter(item => item.priority === 'P1').length) : '—'}</strong><em>En los casos cargados</em></div></div><div className="op-summary"><span className="blue"><Clock3 size={19} /></span><div><small>Última consulta</small><strong className="op-summary-time">{queueAt ? dateLabel(queueAt) : '—'}</strong><em>Actualización manual</em></div></div></div>
          <section className="op-card op-queue-card"><div className="op-card-title"><div><span className="op-kicker">PRIORIZACIÓN</span><h2>Casos para revisar</h2></div><span className="op-card-note">La cola del API ordena por prioridad.</span></div>
            <div className="op-filters"><div className="op-status-tabs" role="group" aria-label="Filtrar por estado">{INCIDENT_STATUSES.map(status => <button key={status} className={queueStatus === status ? 'selected' : ''} onClick={() => setQueueStatus(status)}>{label(status)}</button>)}</div><div><label htmlFor="op-queue-zone">Zona</label><select id="op-queue-zone" value={queueZone} onChange={event => setQueueZone(event.target.value)} disabled={zonesState !== 'ready'}><option value="">Todas las zonas</option>{zones.map(zone => <option key={zone.zone_id} value={zone.zone_id}>{zone.name}</option>)}</select></div></div>
            {zonesState === 'error' && <ErrorBlock error={zonesError} onRetry={() => void loadZones()} />}
            {queueState === 'loading' && !incidents.length ? <Loading /> : queueState === 'error' && !incidents.length ? <ErrorBlock error={queueError} onRetry={() => void loadQueue()} /> : incidents.length ? <><div className="op-table"><div className="op-table-head"><span>Prioridad / incidente</span><span>Zona y servicio</span><span>Estado</span><span>Impacto registrado</span><span>Actualizado</span></div>{incidents.map(item => <button className="op-table-row" key={item.incident_id} onClick={() => openIncident(item.incident_id)}><span><Priority value={item.priority} /><b>#{shortId(item.incident_id)}</b></span><span><strong>{zoneName(item.zone_id)}</strong><small>{label(item.service)}</small></span><span><Status value={item.status} /></span><span><strong>{number(item.affected_users)} usuarios</strong><small>{number(item.report_count)} reportes</small></span><span><small>{dateLabel(item.updated_at)}</small><ChevronRight size={17} /></span></button>)}</div>{queueState === 'error' && <ErrorBlock error={queueError} onRetry={() => void loadQueue(queueStatus, queueZone, queueCursor || undefined)} />}</> : queueState === 'ready' && <Empty icon={<Check size={24} />} title="Sin casos en esta consulta" text="Elige otro estado o zona para revisar más incidentes." />}
            {queueCursor && <div className="op-more"><button className="op-button outline" disabled={queueState === 'loading'} onClick={() => void loadQueue(queueStatus, queueZone, queueCursor)}>{queueState === 'loading' && <LoaderCircle className="spin" size={15} />} Cargar más casos</button></div>}
          </section>
        </>}
        {view === 'incident' && <>
          <button className="op-back" onClick={() => navigate('queue')}><ArrowLeft size={16} /> Volver a la bandeja</button>
          {incidentState === 'loading' && !incident ? <Loading text="Cargando evidencia del incidente…" /> : incidentState === 'error' && !incident ? <ErrorBlock error={incidentError} onRetry={() => incidentId && void loadIncident(incidentId)} /> : incident && <>
            <div className="op-heading op-detail-heading"><div><span className="op-kicker">INCIDENTE OPERATIVO</span><h1>Incidente #{shortId(incident.incident_id)}</h1><p>{zoneName(incident.zone_id)} · {label(incident.service)} · Abierto {dateLabel(incident.opened_at)}</p></div><div className="op-heading-badges"><Priority value={incident.priority} /><Status value={incident.status} /></div></div>
            {incident.review_required && <div className="op-warning"><CircleAlert size={19} />Este caso requiere revisión humana antes de continuar.</div>}
            <div className="op-detail-grid"><div className="op-detail-column"><section className="op-card"><div className="op-card-title"><div><span className="op-kicker">EVIDENCIA ACTUAL</span><h2>Resumen técnico y colectivo</h2></div><Activity size={22} /></div><div className="op-fields"><Field title="Usuarios afectados registrados" value={number(incident.affected_users)} /><Field title="Reportes asociados" value={number(incident.report_count)} /><Field title="Detección inicial" value={label(incident.detected_by)} /><Field title="Peor estado de antena" value={label(incident.worst_antenna_state)} /><Field title="Recuperación técnica" value={incident.tech_recovered ? 'Registrada; pendiente de decisión operativa' : 'No registrada'} /><Field title="Última actualización" value={dateLabel(incident.updated_at)} /></div><p className="op-context-note">Una recuperación técnica no restablece ni cierra el incidente automáticamente. La prioridad y los conteos proceden del API.</p></section>
              <section className="op-card"><div className="op-card-title"><div><span className="op-kicker">INFRAESTRUCTURA</span><h2>Antenas vinculadas</h2></div><RadioTower size={22} /></div>{incident.links?.antennas?.length ? <div className="op-antenna-list">{incident.links.antennas.map((antenna, index) => <div key={`${antenna.antenna_id}-${index}`}><strong>{antenna.antenna_id || 'Antena sin ID'}</strong><span>{label(antenna.state)}</span><small>{antenna.recovered_at ? `Recuperada ${dateLabel(antenna.recovered_at)}` : `Vinculada ${dateLabel(antenna.linked_at)}`}</small></div>)}</div> : <p className="op-muted">Aún no hay antenas vinculadas. Un incidente colectivo puede existir sin anomalía técnica.</p>}</section>
              <section className="op-card"><div className="op-card-title"><div><span className="op-kicker">AUDITORÍA</span><h2>Historial del incidente</h2></div><Clock3 size={21} /></div><Timeline entries={incident.history} fallbackStatus={incident.status} fallbackAt={incident.opened_at} /></section>
            </div><div className="op-detail-column"><TransitionForm entityId={incident.incident_id} current={incident.status} options={INCIDENT_NEXT[incident.status as IncidentStatus] || []} busy={incidentSaving} error={incidentActionError} success={incidentSaved} onApply={applyIncident} />
              <section className="op-card op-ai-card"><div className="op-card-title"><div><span className="op-kicker">APOYO DE IA</span><h2>Sugerencia de análisis</h2></div><Lightbulb size={22} /></div><p>Solicita hipótesis para contrastarlas con la evidencia. La decisión sigue siendo del operador.</p><button className="op-button outline" disabled={suggestionState === 'loading'} onClick={() => void loadSuggestion()}>{suggestionState === 'loading' ? <LoaderCircle className="spin" size={16} /> : <Lightbulb size={16} />} Solicitar sugerencia</button>{suggestionState === 'error' && <ErrorBlock error={suggestionError} onRetry={() => void loadSuggestion()} />}{suggestionState === 'ready' && suggestion && (suggestion.available && suggestion.hypotheses?.length ? <div className="op-hypotheses">{suggestion.hypotheses.map((item, index) => <div key={`${item.title}-${index}`}><strong>{item.title}</strong><p>{item.rationale}</p></div>)}<small>Generada {dateLabel(suggestion.generated_at)} · {suggestion.model || 'Modelo no indicado'}</small></div> : <div className="op-neutral" role="status">La sugerencia no está disponible ahora. Puedes continuar con la evidencia registrada.</div>)}</section>
              <div className="op-aside-note"><MapPin size={18} /><span>El estado público de Azure es un espejo por zona. Usa este detalle de AWS para decidir sobre el incidente.</span></div>
            </div></div>
          </>}
        </>}
        {view === 'reports' && <>
          <div className="op-heading"><div><span className="op-kicker">ATENCIÓN INDIVIDUAL</span><h1>Reportes por zona</h1><p>Consulta y actualiza el historial de cada reporte de cliente.</p></div><button className="op-button outline" disabled={!reportZone || reportsState === 'loading'} onClick={() => void loadReports()}><RefreshCw size={16} /> Actualizar</button></div>
          <section className="op-card"><div className="op-report-tools"><div><label htmlFor="op-report-zone">Zona de consulta</label><select id="op-report-zone" value={reportZone} onChange={event => setReportZone(event.target.value)} disabled={zonesState !== 'ready'}>{zones.map(zone => <option key={zone.zone_id} value={zone.zone_id}>{zone.name}</option>)}</select></div><form onSubmit={event => { event.preventDefault(); if (reportLookup.trim()) openReport(reportLookup.trim()) }}><label htmlFor="op-report-id">Buscar por identificador exacto</label><div><input id="op-report-id" value={reportLookup} onChange={event => setReportLookup(event.target.value)} placeholder="ID completo del reporte" /><button className="op-button primary" type="submit" disabled={!reportLookup.trim()}><Search size={16} /> Abrir</button></div></form></div><p className="op-context-note">La lista contiene reportes de la zona elegida; no implica que todos estén vinculados al mismo incidente.</p>
            {zonesState === 'loading' ? <Loading text="Cargando zonas…" /> : zonesState === 'error' ? <ErrorBlock error={zonesError} onRetry={() => void loadZones()} /> : !reportZone ? <Empty icon={<MapPin size={25} />} title="No hay zonas disponibles" text="El catálogo no devolvió zonas para consultar." /> : reportsState === 'loading' && !reports.length ? <Loading /> : reportsState === 'error' && !reports.length ? <ErrorBlock error={reportsError} onRetry={() => void loadReports()} /> : reports.length ? <div className="op-report-list">{reports.map(item => <button key={item.report_id} onClick={() => openReport(item.report_id)}><span className="op-report-icon"><FileText size={20} /></span><span><strong>{label(item.problem_type)}</strong><small>#{shortId(item.report_id)} · {label(item.service)} · {dateLabel(item.created_at)}</small></span><Status value={item.status} /><ChevronRight size={18} /></button>)}</div> : reportsState === 'ready' && <Empty icon={<FileText size={24} />} title="Sin reportes en esta zona" text="Elige otra zona o busca un ID de reporte conocido." />}
            {reportsState === 'error' && reports.length > 0 && <ErrorBlock error={reportsError} onRetry={() => void loadReports(reportZone, reportsCursor || undefined)} />}{reportsCursor && <div className="op-more"><button className="op-button outline" disabled={reportsState === 'loading'} onClick={() => void loadReports(reportZone, reportsCursor)}>{reportsState === 'loading' && <LoaderCircle className="spin" size={15} />} Cargar más reportes</button></div>}
          </section>
        </>}
        {view === 'report' && <>
          <button className="op-back" onClick={() => navigate('reports')}><ArrowLeft size={16} /> Volver a reportes</button>
          {reportState === 'loading' && !report ? <Loading text="Cargando reporte…" /> : reportState === 'error' && !report ? <ErrorBlock error={reportError} onRetry={() => reportId && void loadReport(reportId)} /> : report && <><div className="op-heading op-detail-heading"><div><span className="op-kicker">REPORTE DE CLIENTE</span><h1>Reporte #{shortId(report.report_id)}</h1><p>{zoneName(report.zone_id)} · {label(report.service)} · Creado {dateLabel(report.created_at)}</p></div><Status value={report.status} /></div><div className="op-detail-grid"><div className="op-detail-column"><section className="op-card"><div className="op-card-title"><div><span className="op-kicker">SOLICITUD</span><h2>Información del reporte</h2></div><FileText size={21} /></div><div className="op-fields"><Field title="Tipo de problema" value={label(report.problem_type)} /><Field title="Servicio" value={label(report.service)} /><Field title="Zona" value={zoneName(report.zone_id)} /><Field title="Ocurrió" value={dateLabel(report.occurred_at)} /><Field title="Referencia de ubicación" value={report.location_text || 'No indicada'} /><Field title="Servicio asociado" value={report.service_number ? `Termina en ${report.service_number.slice(-4)}` : 'No disponible'} /></div><div className="op-description"><small>DESCRIPCIÓN</small><p>{report.description || 'No hay descripción disponible.'}</p></div>{report.incident_id && <div className="op-related">Relacionado con incidencia #{shortId(report.incident_id)}. <button className="op-link" onClick={() => openIncident(report.incident_id!)}>Abrir incidencia <ArrowRight size={15} /></button></div>}</section><section className="op-card"><div className="op-card-title"><div><span className="op-kicker">AUDITORÍA</span><h2>Historial del reporte</h2></div><Clock3 size={21} /></div><Timeline entries={report.history} fallbackStatus={report.status} fallbackAt={report.created_at} /></section></div><div className="op-detail-column"><TransitionForm entityId={report.report_id} current={report.status} options={REPORT_NEXT[report.status] || []} busy={reportSaving} error={reportActionError} success={reportSaved} onApply={applyReport} /><div className="op-aside-note"><Users size={18} /><span>El reporte individual y el incidente de zona siguen ciclos de estado independientes.</span></div></div></div></>}
        </>}
        {view === 'trends' && <>
          <div className="op-heading"><div><span className="op-kicker">ANÁLISIS DE LA RED</span><h1>Tendencias</h1><p>Datos operativos del periodo seleccionado, sin cifras de ejemplo.</p></div><button className="op-button outline" disabled={trendsState === 'loading'} onClick={() => void loadTrends()}><RefreshCw size={16} /> Actualizar</button></div><div className="op-period" role="group" aria-label="Periodo de tendencias"><button className={trendsDays === 7 ? 'active' : ''} onClick={() => setTrendsDays(7)}>Últimos 7 días</button><button className={trendsDays === 30 ? 'active' : ''} onClick={() => setTrendsDays(30)}>Últimos 30 días</button></div>
          {trendsState === 'loading' ? <Loading text="Calculando tendencias del periodo…" /> : trendsState === 'error' ? <ErrorBlock error={trendsError} onRetry={() => void loadTrends()} /> : trends && <><div className="op-trend-metrics"><div><span><RadioTower size={21} /></span><small>Detección por antena</small><strong>{number(trends.deteccion?.detected_by_antenna)}</strong><p>Incidentes del periodo</p></div><div><span><Users size={21} /></span><small>Detección por usuarios</small><strong>{number(trends.deteccion?.detected_by_users)}</strong><p>Incidentes del periodo</p></div><div><span><Clock3 size={21} /></span><small>Demora media de detección</small><strong>{number(trends.deteccion?.avg_lag_seconds)} s</strong><p>Según casos con medición</p></div></div><div className="op-trend-grid"><section className="op-card"><div className="op-card-title"><div><span className="op-kicker">ACTIVIDAD</span><h2>Zonas con más reportes</h2></div><MapPin size={21} /></div><Bars rows={trends.top_zonas.map(item => ({ id: item.zone_id, name: item.name || item.zone_id, count: item.reports, secondary: `${number(item.incidents)} incidentes` }))} /></section><section className="op-card"><div className="op-card-title"><div><span className="op-kicker">TELEMETRÍA</span><h2>Antenas con más episodios</h2></div><RadioTower size={21} /></div><Bars rows={trends.top_antenas.map(item => ({ id: item.antenna_id, name: item.antenna_id, count: item.episodes, secondary: zoneName(item.zone_id) }))} /></section><section className="op-card"><div className="op-card-title"><div><span className="op-kicker">SOLICITUDES</span><h2>Tipos de problema</h2></div><FileText size={21} /></div><Bars rows={trends.top_tipos.map(item => ({ id: item.problem_type, name: label(item.problem_type), count: item.count }))} /></section><section className="op-card"><div className="op-card-title"><div><span className="op-kicker">RECURRENCIA</span><h2>Antenas para revisar</h2></div><CircleAlert size={21} /></div>{trends.recurrentes?.length ? <div className="op-recurrence">{trends.recurrentes.map(item => <div key={item.antenna_id}><strong>{item.antenna_id}</strong><span>{zoneName(item.zone_id)}</span><b>{number(item.episodes_7d)} episodios / 7 días</b></div>)}</div> : <p className="op-muted">No hay antenas que alcancen el umbral de recurrencia.</p>}</section></div></>}
        </>}
      </main><footer className="op-footer"><span>© 2026 Red TeleCorp · Centro de operaciones</span><span>Los datos se consultan directamente en AWS; Azure ofrece una vista pública independiente.</span></footer>
    </div>
  </div>
}
