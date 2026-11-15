import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  Activity, ArrowLeft, ArrowRight, ArrowUpRight, Bell, Check, CheckCircle2,
  ChevronRight, CircleAlert, Clock3, FilePlus2, FileText, Headphones,
  LayoutDashboard, LoaderCircle, LogOut, MapPin, Menu, RadioTower,
  RefreshCw, ShieldCheck, Signal, X,
} from 'lucide-react'
import { api, ApiError, readableError } from './api'
import type { CreateReportBody, Incident, Report, Session, Zone } from './types'

type View = 'home' | 'new' | 'reports' | 'detail' | 'zone' | 'success'
type LoadState = 'idle' | 'loading' | 'ready' | 'error'

const AZURE_STATUS_URL = 'https://mango-ground-073e60210.3.azurestaticapps.net'
const STATUS_LABEL: Record<string, string> = {
  REGISTRADA: 'Registrada', EN_REVISION: 'En revisión', EN_ATENCION: 'En atención',
  SOLUCIONADA: 'Solucionada', CERRADA: 'Cerrada', EVALUACION: 'En evaluación',
  CONFIRMADO: 'Incidencia identificada', RESTABLECIDO: 'Servicio restablecido',
}
const PROBLEM_OPTIONS = [
  { value: 'SIN_INTERNET', label: 'Sin internet' },
  { value: 'SIN_SENAL', label: 'Sin señal' },
  { value: 'LLAMADAS', label: 'Problemas con llamadas' },
  { value: 'SMS', label: 'Problemas con mensajes' },
  { value: 'LENTITUD', label: 'Servicio lento' },
  { value: 'OTRO', label: 'Otro inconveniente' },
]

function dateLabel(value?: string) {
  if (!value) return 'Fecha no disponible'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Fecha no disponible' : date.toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })
}

function localDateTime(date = new Date()) {
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function StatusBadge({ status }: { status: string }) {
  const tone = status === 'CERRADA' || status === 'CERRADO' || status === 'SOLUCIONADA' || status === 'RESTABLECIDO'
    ? 'resolved'
    : status === 'REGISTRADA' || status === 'EVALUACION' ? 'waiting' : 'progress'
  return <span className={`status-badge ${tone}`}><span className="status-dot" />{STATUS_LABEL[status] || status}</span>
}

function ErrorPanel({ error, onRetry, compact = false }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  const { message, detail } = readableError(error)
  return <div className={`error-panel ${compact ? 'compact' : ''}`} role="alert">
    <div className="error-icon"><CircleAlert size={19} /></div>
    <div><strong>{message}</strong><p>{detail}</p>{onRetry && <button className="text-button" type="button" onClick={onRetry}>Volver a intentar <ArrowRight size={15} /></button>}</div>
  </div>
}

function EmptyState({ icon, title, text, action }: { icon: ReactNode; title: string; text: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{text}</p>{action}</div>
}

function LoadingState({ label = 'Cargando información…' }: { label?: string }) {
  return <div className="loading-state" role="status"><LoaderCircle className="spin" size={20} />{label}</div>
}

function Brand({ light = false }: { light?: boolean }) {
  return <div className={`brand ${light ? 'brand-light' : ''}`}><div className="brand-mark"><Signal size={21} strokeWidth={2.8} /></div><div><strong>red<span>telecorp</span></strong><small>PORTAL DE CLIENTES</small></div></div>
}

function LoginScreen({ onLogin, notice }: { onLogin: (session: Session) => void; notice: string }) {
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const result = await api.login(identifier.trim(), password)
      if (!result.token || !Number.isFinite(result.expires_in)) throw new ApiError('El inicio de sesión devolvió datos incompletos.', 200, 'INVALID_RESPONSE', '/auth/login')
      if (result.role !== 'CUSTOMER') throw new ApiError('Esta primera versión del portal es solo para clientes. Tu cuenta de operador no se ha modificado.', 403, 'ROLE', '/auth/login')
      onLogin({ token: result.token, role: 'CUSTOMER', name: result.name || 'Cliente', expiresAt: Date.now() + result.expires_in * 1000 })
    } catch (caught) {
      setError(caught)
    } finally {
      setSubmitting(false)
    }
  }

  return <main className="login-layout">
    <section className="login-story" aria-label="Red TeleCorp">
      <div className="story-top"><Brand light /><span className="story-tag"><span /> Centro de servicio</span></div>
      <div className="story-content"><div className="eyebrow story-eyebrow"><span className="eyebrow-line" /> CONECTADOS CONTIGO</div>
        <h1>Tu conexión importa.<br /><em>Tu voz también.</em></h1>
        <p>Reporta lo que ocurre con tu servicio y sigue cada paso de la atención desde un solo lugar.</p>
        <div className="story-features"><div><span><FilePlus2 size={18} /></span><div><strong>Reporta en minutos</strong><small>Cuéntanos qué sucede y dónde.</small></div></div><div><span><Activity size={18} /></span><div><strong>Sigue el progreso</strong><small>Consulta el estado y su historial.</small></div></div></div>
      </div>
      <div className="orbit" aria-hidden="true"><div className="orbit-ring orbit-one" /><div className="orbit-ring orbit-two" /><div className="orbit-ring orbit-three" /><div className="orbit-core"><RadioTower size={52} /></div><i className="orbit-point point-one" /><i className="orbit-point point-two" /><i className="orbit-point point-three" /></div>
      <div className="story-bottom"><span>Red TeleCorp · Red que escucha</span><span>Atención digital 24/7</span></div>
    </section>
    <section className="login-side"><div className="login-mobile-brand"><Brand /></div><div className="login-box"><div className="login-kicker"><span className="small-line" /> BIENVENIDO DE NUEVO</div><h2>Accede a tu portal</h2><p className="login-intro">Ingresa con tu identificación y contraseña para consultar tus reportes.</p>
      {notice && <div className="notice-bar" role="status"><Clock3 size={17} />{notice}</div>}
      <form onSubmit={submit} className="login-form"><label htmlFor="identifier">Identificación</label><input id="identifier" autoComplete="username" inputMode="numeric" placeholder="Tu número de identificación" maxLength={64} value={identifier} onChange={event => setIdentifier(event.target.value)} required />
        <label htmlFor="password">Contraseña</label><input id="password" type="password" autoComplete="current-password" placeholder="Ingresa tu contraseña" maxLength={256} value={password} onChange={event => setPassword(event.target.value)} required />
        {error !== null && <ErrorPanel error={error} compact />}
        <button className="primary-button login-button" type="submit" disabled={submitting}>{submitting ? <><LoaderCircle className="spin" size={18} /> Accediendo…</> : <>Ingresar al portal <ArrowRight size={18} /></>}</button>
      </form><div className="login-help"><ShieldCheck size={19} /><span>Tu información se consulta en una sesión protegida. La sesión vence a los 15 minutos.</span></div>
    </div><div className="login-footer">¿Buscas información general? <a href={AZURE_STATUS_URL} target="_blank" rel="noopener noreferrer">Ver estado público de la red <ArrowUpRight size={14} /></a></div></section>
  </main>
}

function ReportForm({ zones, zonesState, token, onCreated, onUnauthorized }: { zones: Zone[]; zonesState: LoadState; token: string; onCreated: (report: Report) => void; onUnauthorized: () => void }) {
  const [serviceNumber, setServiceNumber] = useState('')
  const [zoneId, setZoneId] = useState('')
  const [service, setService] = useState<'MOVIL' | 'INTERNET'>('INTERNET')
  const [problemType, setProblemType] = useState('SIN_INTERNET')
  const [occurredAt, setOccurredAt] = useState(localDateTime())
  const [location, setLocation] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const keyRef = useRef<string | null>(null)

  function changed<T>(setter: (value: T) => void, value: T) { setter(value); keyRef.current = null; setError(null) }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const occurred = new Date(occurredAt)
    if (!zoneId || !Number.isFinite(occurred.getTime())) { setError(new ApiError('Elige una zona y una fecha válidas.', 400, 'VALIDATION', '/reportes')); return }
    if (occurred.getTime() > Date.now() || occurred.getTime() < Date.now() - 30 * 86_400_000) { setError(new ApiError('La fecha debe estar entre hace 30 días y ahora.', 400, 'VALIDATION', '/reportes')); return }
    const body: CreateReportBody = { service_number: serviceNumber.trim(), zone_id: zoneId, service, problem_type: problemType, description: description.trim(), location_text: location.trim(), occurred_at: occurred.toISOString() }
    keyRef.current ||= crypto.randomUUID()
    setSubmitting(true)
    try {
      const created = await api.createReport(token, body, keyRef.current)
      if (!created.report_id) throw new ApiError('El servidor confirmó la solicitud, pero no devolvió el identificador.', 200, 'INVALID_RESPONSE', '/reportes')
      keyRef.current = null
      onCreated(created)
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) onUnauthorized()
      else setError(caught)
    } finally { setSubmitting(false) }
  }

  return <div className="page-grid form-grid"><div><div className="page-heading"><div className="eyebrow">NUEVO REPORTE</div><h1>Cuéntanos qué está pasando</h1><p>Necesitamos algunos datos para ubicar el inconveniente y comenzar la revisión.</p></div>
    <form className="report-form surface" onSubmit={submit}>
      <div className="form-section-heading"><span>01</span><div><h2>Tu servicio</h2><p>Elige el servicio afectado y el número asociado.</p></div></div>
      <div className="form-row"><div className="field"><label htmlFor="service">Servicio afectado</label><select id="service" value={service} onChange={event => { const value = event.target.value as 'MOVIL' | 'INTERNET'; changed(setService, value); setProblemType(value === 'INTERNET' ? 'SIN_INTERNET' : 'SIN_SENAL') }}><option value="INTERNET">Internet</option><option value="MOVIL">Telefonía móvil</option></select></div><div className="field"><label htmlFor="service-number">Número asociado al servicio</label><input id="service-number" value={serviceNumber} onChange={event => changed(setServiceNumber, event.target.value)} placeholder="Ej. 987654321" maxLength={20} required /></div></div>
      <div className="form-divider" /><div className="form-section-heading"><span>02</span><div><h2>¿Dónde y cuándo?</h2><p>Una referencia aproximada es suficiente.</p></div></div>
      <div className="form-row"><div className="field"><label htmlFor="zone">Zona</label><select id="zone" value={zoneId} onChange={event => changed(setZoneId, event.target.value)} required disabled={zonesState !== 'ready' || zones.length === 0}><option value="">Selecciona tu zona</option>{zones.map(zone => <option value={zone.zone_id} key={zone.zone_id}>{zone.name}</option>)}</select></div><div className="field"><label htmlFor="occurred">Fecha y hora del inconveniente</label><input id="occurred" type="datetime-local" value={occurredAt} max={localDateTime()} onChange={event => changed(setOccurredAt, event.target.value)} required /></div></div>
      <div className="field"><label htmlFor="location">Ubicación aproximada</label><input id="location" value={location} onChange={event => changed(setLocation, event.target.value)} placeholder="Ej. Cerca del parque principal" maxLength={200} required /><small>Evita indicar tu dirección exacta.</small></div>
      <div className="form-divider" /><div className="form-section-heading"><span>03</span><div><h2>¿Qué ocurrió?</h2><p>Tu descripción ayudará a nuestro equipo a revisar el caso.</p></div></div>
      <div className="field"><label htmlFor="problem">Tipo de problema</label><select id="problem" value={problemType} onChange={event => changed(setProblemType, event.target.value)}>{PROBLEM_OPTIONS.map(option => <option value={option.value} key={option.value}>{option.label}</option>)}</select></div>
      <div className="field"><label htmlFor="description">Descripción</label><textarea id="description" value={description} onChange={event => changed(setDescription, event.target.value)} placeholder="Describe brevemente lo que sucede…" maxLength={1000} rows={5} required /><small>{description.length}/1000 caracteres</small></div>
      {zonesState === 'error' && <div className="form-warning"><CircleAlert size={17} />No se pudieron cargar las zonas. Vuelve al inicio y reintenta.</div>}
      {error !== null && <ErrorPanel error={error} compact />}
      <div className="form-actions"><p><ShieldCheck size={17} /> Tu reporte será visible solo para ti y para operaciones.</p><button className="primary-button" disabled={submitting || zones.length === 0} type="submit">{submitting ? <><LoaderCircle className="spin" size={17} /> Enviando…</> : <>Enviar reporte <ArrowRight size={17} /></>}</button></div>
    </form></div><aside className="form-aside"><div className="aside-card"><div className="aside-icon"><Headphones size={22} /></div><h3>Estamos para ayudarte</h3><p>Después de enviarlo recibirás un número de reporte. Podrás consultar los cambios desde «Mis reportes».</p><div className="aside-divider" /><div className="aside-step"><span>1</span> Registramos tu solicitud</div><div className="aside-step"><span>2</span> Revisamos la información</div><div className="aside-step"><span>3</span> Te mostramos el avance</div></div></aside></div>
}

function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [loginNotice, setLoginNotice] = useState('')
  const [view, setView] = useState<View>('home')
  const [menuOpen, setMenuOpen] = useState(false)
  const [zones, setZones] = useState<Zone[]>([])
  const [zonesState, setZonesState] = useState<LoadState>('idle')
  const [zonesError, setZonesError] = useState<unknown>(null)
  const [zoneId, setZoneId] = useState('')
  const [reports, setReports] = useState<Report[]>([])
  const [reportsCursor, setReportsCursor] = useState<string | null>(null)
  const [reportsState, setReportsState] = useState<LoadState>('idle')
  const [reportsError, setReportsError] = useState<unknown>(null)
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [incidentsCursor, setIncidentsCursor] = useState<string | null>(null)
  const [incidentsState, setIncidentsState] = useState<LoadState>('idle')
  const [incidentsError, setIncidentsError] = useState<unknown>(null)
  const [detail, setDetail] = useState<Report | null>(null)
  const [detailState, setDetailState] = useState<LoadState>('idle')
  const [detailError, setDetailError] = useState<unknown>(null)
  const [created, setCreated] = useState<Report | null>(null)

  function unauthorized() { setSession(null); setLoginNotice('Tu sesión terminó. Inicia sesión para continuar.') }
  function catchError(error: unknown, setError: (error: unknown) => void, setState: (state: LoadState) => void) {
    if (error instanceof ApiError && error.status === 401) unauthorized()
    else { setError(error); setState('error') }
  }

  async function loadZones(token: string) {
    setZonesState('loading'); setZonesError(null)
    try { const result = await api.zones(token); if (!Array.isArray(result.items)) throw new ApiError('Lista de zonas inválida.', 200, 'INVALID_RESPONSE', '/zonas'); setZones(result.items); setZoneId(old => old || result.items[0]?.zone_id || ''); setZonesState('ready') }
    catch (error) { catchError(error, setZonesError, setZonesState) }
  }
  async function loadReports(token: string, cursor?: string) {
    setReportsState('loading'); setReportsError(null)
    try { const result = await api.reports(token, cursor); if (!Array.isArray(result.items)) throw new ApiError('Lista de reportes inválida.', 200, 'INVALID_RESPONSE', '/reportes'); setReports(old => cursor ? [...old, ...result.items] : result.items); setReportsCursor(result.next_cursor ?? null); setReportsState('ready') }
    catch (error) { catchError(error, setReportsError, setReportsState) }
  }
  async function loadIncidents(token: string, selectedZone: string, cursor?: string) {
    setIncidentsState('loading'); setIncidentsError(null)
    try { const result = await api.incidents(token, selectedZone, cursor); if (!Array.isArray(result.items)) throw new ApiError('Lista de incidencias inválida.', 200, 'INVALID_RESPONSE', '/incidentes'); setIncidents(old => cursor ? [...old, ...result.items] : result.items); setIncidentsCursor(result.next_cursor ?? null); setIncidentsState('ready') }
    catch (error) { catchError(error, setIncidentsError, setIncidentsState) }
  }
  async function openReport(id: string) {
    if (!session) return
    setView('detail'); setDetail(null); setDetailError(null); setDetailState('loading'); setMenuOpen(false)
    try { const result = await api.report(session.token, id); if (!result.report_id) throw new ApiError('Detalle de reporte inválido.', 200, 'INVALID_RESPONSE', `/reportes/${id}`); setDetail(result); setDetailState('ready') }
    catch (error) { catchError(error, setDetailError, setDetailState) }
  }

  useEffect(() => { if (!session) return; void loadZones(session.token); void loadReports(session.token) }, [session])
  useEffect(() => { if (!session || !zoneId) return; setIncidents([]); void loadIncidents(session.token, zoneId) }, [session, zoneId])
  useEffect(() => { if (!session) return; const timer = window.setInterval(() => { if (Date.now() >= session.expiresAt) unauthorized() }, 10_000); return () => window.clearInterval(timer) }, [session])

  if (!session) return <LoginScreen notice={loginNotice} onLogin={value => { setSession(value); setLoginNotice(''); setView('home') }} />

  const selectedZone = zones.find(zone => zone.zone_id === zoneId)
  const activeReports = reports.filter(report => !['SOLUCIONADA', 'CERRADA'].includes(report.status)).length
  const navItems: { id: View; label: string; icon: ReactNode }[] = [
    { id: 'home', label: 'Inicio', icon: <LayoutDashboard size={19} /> },
    { id: 'new', label: 'Nuevo reporte', icon: <FilePlus2 size={19} /> },
    { id: 'reports', label: 'Mis reportes', icon: <FileText size={19} /> },
    { id: 'zone', label: 'Estado de mi zona', icon: <MapPin size={19} /> },
  ]
  function navigate(next: View) { setView(next); setMenuOpen(false) }

  return <div className="app-shell">
    {menuOpen && <button className="mobile-overlay" aria-label="Cerrar menú" onClick={() => setMenuOpen(false)} />}
    <aside className={`sidebar ${menuOpen ? 'open' : ''}`}><div className="sidebar-top"><Brand light /><button className="mobile-close icon-button" onClick={() => setMenuOpen(false)} aria-label="Cerrar menú"><X size={20} /></button></div>
      <div className="sidebar-label">MI ESPACIO</div><nav aria-label="Navegación principal">{navItems.map(item => <button key={item.id} className={`nav-link ${view === item.id || (item.id === 'reports' && view === 'detail') ? 'active' : ''}`} onClick={() => navigate(item.id)}>{item.icon}<span>{item.label}</span>{item.id === 'new' && <PlusSymbol />}</button>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-help"><div className="sidebar-help-icon"><Headphones size={21} /></div><strong>¿Necesitas ayuda?</strong><p>Consulta el avance de tus reportes en cualquier momento.</p></div><a href={AZURE_STATUS_URL} target="_blank" rel="noopener noreferrer" className="sidebar-external">Estado público de la red <ArrowUpRight size={17} /></a></div>
    </aside>
    <div className="main-area"><header className="topbar"><div className="topbar-left"><button className="menu-toggle icon-button" onClick={() => setMenuOpen(true)} aria-label="Abrir menú"><Menu size={23} /></button><span>Centro de servicio</span><ChevronRight size={15} /><strong>{view === 'home' ? 'Inicio' : view === 'new' ? 'Nuevo reporte' : view === 'zone' ? 'Estado de mi zona' : view === 'success' ? 'Confirmación' : 'Mis reportes'}</strong></div><div className="topbar-right"><span className="live-pill"><span /> Portal de clientes</span><div className="avatar" aria-hidden="true">{session.name.slice(0, 1).toUpperCase()}</div><span className="topbar-name">{session.name}</span><button className="logout icon-button" onClick={() => { setSession(null); setLoginNotice('Has cerrado sesión.') }} aria-label="Cerrar sesión" title="Cerrar sesión"><LogOut size={19} /></button></div></header>
      <main className="content">
        {view === 'home' && <><div className="welcome-row"><div><div className="eyebrow">TU CENTRO DE SERVICIO</div><h1>Hola, {session.name.split(' ')[0]} <span className="wave">✳</span></h1><p>Estamos aquí para ayudarte a mantenerte conectado.</p></div><button className="outline-button desktop-action" onClick={() => { void loadReports(session.token); void loadZones(session.token); if (zoneId) void loadIncidents(session.token, zoneId) }}><RefreshCw size={16} /> Actualizar</button></div>
          <div className="hero-card"><div className="hero-copy"><span className="hero-kicker"><span /> ESTAMOS CONTIGO</span><h2>¿Tienes algún problema<br />con tu servicio?</h2><p>Cuéntanos lo que pasa y podrás seguir cada avance desde aquí.</p><button className="hero-button" onClick={() => navigate('new')}>Crear un reporte <ArrowRight size={18} /></button></div><div className="hero-art" aria-hidden="true"><div className="hero-ring one" /><div className="hero-ring two" /><div className="hero-ring three" /><div className="hero-center"><RadioTower size={48} /></div><span className="hero-signal signal-one" /><span className="hero-signal signal-two" /></div></div>
          <div className="metric-grid"><div className="metric-card"><div className="metric-icon blue"><FileText size={21} /></div><div><small>Reportes cargados</small><strong>{reportsState === 'ready' ? reports.length : '—'}</strong><span>En la página actual</span></div></div><div className="metric-card"><div className="metric-icon amber"><Clock3 size={21} /></div><div><small>En seguimiento</small><strong>{reportsState === 'ready' ? activeReports : '—'}</strong><span>De los reportes cargados</span></div></div><div className="metric-card"><div className="metric-icon teal"><MapPin size={21} /></div><div><small>Zona consultada</small><strong className="metric-zone">{selectedZone?.name || '—'}</strong><span>{selectedZone ? 'Estado disponible abajo' : 'Selecciona una zona'}</span></div></div></div>
          <div className="dashboard-grid"><section className="surface dashboard-section"><div className="section-head"><div><h2>Mis reportes recientes</h2><p>Revisa el estado de tus solicitudes.</p></div><button className="text-button" onClick={() => navigate('reports')}>Ver todos <ArrowRight size={16} /></button></div>{reportsState === 'loading' && reports.length === 0 ? <LoadingState /> : reportsState === 'error' && reports.length === 0 ? <ErrorPanel error={reportsError} onRetry={() => void loadReports(session.token)} /> : reports.length ? <div className="report-list compact-list">{reports.slice(0, 3).map(report => <ReportRow key={report.report_id} report={report} zones={zones} onOpen={() => void openReport(report.report_id)} />)}</div> : <EmptyState icon={<FileText size={25} />} title="Aún no tienes reportes" text="Cuando registres uno, aparecerá aquí para que puedas seguirlo." action={<button className="text-button" onClick={() => navigate('new')}>Crear mi primer reporte <ArrowRight size={15} /></button>} />}</section>
            <section className="surface dashboard-section zone-preview"><div className="section-head"><div><h2>Estado de tu zona</h2><p>Consulta las incidencias de servicio.</p></div><div className="section-icon"><MapPin size={19} /></div></div><label className="visually-hidden" htmlFor="home-zone">Zona</label><select className="zone-select" id="home-zone" value={zoneId} onChange={event => setZoneId(event.target.value)} disabled={zonesState !== 'ready'}>{zones.map(zone => <option value={zone.zone_id} key={zone.zone_id}>{zone.name}</option>)}</select>{zonesState === 'error' ? <ErrorPanel error={zonesError} compact onRetry={() => void loadZones(session.token)} /> : incidentsState === 'loading' && incidents.length === 0 ? <LoadingState /> : incidentsState === 'error' ? <ErrorPanel error={incidentsError} compact onRetry={() => void loadIncidents(session.token, zoneId)} /> : <div className="zone-summary"><div className={`zone-status-icon ${incidents.length ? 'attention' : ''}`}>{incidents.length ? <Bell size={22} /> : incidentsCursor ? <Clock3 size={23} /> : <Check size={23} />}</div><strong>{incidents.length ? `${incidents.length} incidencia${incidents.length === 1 ? '' : 's'} visible${incidents.length === 1 ? '' : 's'}` : incidentsCursor ? 'Hay más información por revisar' : 'Sin incidencias visibles'}</strong><p>{incidents.length ? 'Nuestro equipo está revisando el estado de esta zona.' : incidentsCursor ? 'La consulta tiene más páginas. Revisa el detalle para continuar.' : 'No hay incidencias activas visibles en esta zona.'}</p><button className="text-button" onClick={() => navigate('zone')}>Ver detalle de zona <ArrowRight size={16} /></button></div>}</section></div>
        </>}
        {view === 'new' && <ReportForm zones={zones} zonesState={zonesState} token={session.token} onUnauthorized={unauthorized} onCreated={report => { setCreated(report); setView('success'); void loadReports(session.token) }} />}
        {view === 'success' && created && <div className="success-page"><div className="success-symbol"><CheckCircle2 size={45} /></div><div className="eyebrow">REPORTE RECIBIDO</div><h1>Ya estamos al tanto.</h1><p>Registramos tu solicitud. Puedes volver cuando quieras para consultar cómo avanza.</p><div className="success-reference"><span>NÚMERO DE REPORTE</span><strong>{created.report_id}</strong><StatusBadge status={created.status || 'REGISTRADA'} /></div><div className="success-actions"><button className="primary-button" onClick={() => void openReport(created.report_id)}>Ver mi reporte <ArrowRight size={17} /></button><button className="outline-button" onClick={() => navigate('home')}>Volver al inicio</button></div><small>Recibir el reporte no significa que una falla colectiva ya esté confirmada.</small></div>}
        {view === 'reports' && <><div className="page-heading heading-actions"><div><div className="eyebrow">HISTORIAL PERSONAL</div><h1>Mis reportes</h1><p>El detalle conserva los cambios de estado de cada solicitud.</p></div><button className="primary-button" onClick={() => navigate('new')}><FilePlus2 size={18} /> Nuevo reporte</button></div><section className="surface list-surface"><div className="list-header"><h2>Solicitudes registradas</h2><span>{reportsState === 'ready' ? `${reports.length} cargadas` : 'Consultando…'}</span></div>{reportsState === 'loading' && reports.length === 0 ? <LoadingState /> : reportsState === 'error' && reports.length === 0 ? <ErrorPanel error={reportsError} onRetry={() => void loadReports(session.token)} /> : reports.length ? <div className="report-list">{reports.map(report => <ReportRow report={report} key={report.report_id} zones={zones} onOpen={() => void openReport(report.report_id)} />)}</div> : <EmptyState icon={<FileText size={26} />} title="Todavía no hay reportes" text="Tu primer reporte aparecerá aquí cuando lo registres." action={<button className="text-button" onClick={() => navigate('new')}>Crear reporte <ArrowRight size={16} /></button>} />}{reportsState === 'error' && reports.length > 0 && <ErrorPanel error={reportsError} compact onRetry={() => void loadReports(session.token, reportsCursor || undefined)} />}{reportsCursor && <div className="load-more"><button className="outline-button" disabled={reportsState === 'loading'} onClick={() => void loadReports(session.token, reportsCursor)}>{reportsState === 'loading' ? <LoaderCircle className="spin" size={16} /> : null} Cargar más reportes</button></div>}</section></>}
        {view === 'detail' && <><button className="back-link" onClick={() => navigate('reports')}><ArrowLeft size={17} /> Volver a mis reportes</button>{detailState === 'loading' ? <LoadingState label="Cargando detalle del reporte…" /> : detailState === 'error' ? <ErrorPanel error={detailError} onRetry={() => { if (detail?.report_id) void openReport(detail.report_id); else navigate('reports') }} /> : detail && <><div className="page-heading detail-heading"><div><div className="eyebrow">DETALLE DEL REPORTE</div><h1>Reporte <span>#{detail.report_id.slice(0, 8)}</span></h1><p>Creado el {dateLabel(detail.created_at)}</p></div><StatusBadge status={detail.status} /></div><div className="detail-grid"><section className="surface detail-card"><div className="detail-card-head"><h2>Información del caso</h2><FileText size={21} /></div><div className="detail-data"><div><small>Servicio</small><strong>{detail.service === 'MOVIL' ? 'Telefonía móvil' : detail.service === 'INTERNET' ? 'Internet' : detail.service || 'No disponible'}</strong></div><div><small>Zona</small><strong>{zones.find(zone => zone.zone_id === detail.zone_id)?.name || detail.zone_id || 'No disponible'}</strong></div><div><small>Tipo de problema</small><strong>{PROBLEM_OPTIONS.find(option => option.value === detail.problem_type)?.label || detail.problem_type || 'No disponible'}</strong></div><div><small>Fecha del inconveniente</small><strong>{dateLabel(detail.occurred_at)}</strong></div><div><small>Número de servicio</small><strong>{detail.service_number || 'No disponible'}</strong></div><div><small>Ubicación aproximada</small><strong>{detail.location_text || 'No indicada'}</strong></div></div><div className="description-box"><small>DESCRIPCIÓN</small><p>{detail.description || 'Sin descripción disponible.'}</p></div>{detail.incident_id && <div className="related-box"><Activity size={18} /><span>Este reporte está relacionado con una incidencia de zona. Puedes consultar su estado en «Estado de mi zona».</span></div>}</section><section className="surface timeline-card"><h2>Seguimiento</h2><p className="timeline-intro">Cada cambio se registra con su fecha.</p><div className="timeline">{(detail.history || []).length ? detail.history?.map((entry, index) => <div className="timeline-item" key={`${entry.at}-${index}`}><div className="timeline-marker"><Check size={13} /></div><div><strong>{STATUS_LABEL[entry.to_status] || entry.to_status}</strong><span>{dateLabel(entry.at)}</span>{entry.reason && <p>{entry.reason}</p>}</div></div>) : <div className="timeline-item"><div className="timeline-marker"><Check size={13} /></div><div><strong>{STATUS_LABEL[detail.status] || detail.status}</strong><span>{dateLabel(detail.created_at)}</span></div></div>}</div><div className="timeline-note"><Clock3 size={17} /> El estado puede cambiar después de que nuestro equipo revise tu solicitud.</div></section></div></>}</>}
        {view === 'zone' && <><div className="page-heading"><div className="eyebrow">INFORMACIÓN DE LA RED</div><h1>Estado de mi zona</h1><p>Información general de incidentes visibles en la zona seleccionada.</p></div><section className="surface zone-page-card"><div className="zone-page-top"><div><label htmlFor="zone-page-select">Selecciona una zona</label><select id="zone-page-select" className="zone-select" value={zoneId} onChange={event => setZoneId(event.target.value)} disabled={zonesState !== 'ready'}>{zones.map(zone => <option key={zone.zone_id} value={zone.zone_id}>{zone.name}</option>)}</select></div><MapPin size={23} /></div>{zonesState === 'loading' ? <LoadingState /> : zonesState === 'error' ? <ErrorPanel error={zonesError} onRetry={() => void loadZones(session.token)} /> : !zoneId ? <EmptyState icon={<MapPin size={26} />} title="No hay zonas disponibles" text="El catálogo de zonas todavía no respondió con datos." /> : incidentsState === 'loading' && incidents.length === 0 ? <LoadingState /> : incidentsState === 'error' && incidents.length === 0 ? <ErrorPanel error={incidentsError} onRetry={() => void loadIncidents(session.token, zoneId)} /> : <><div className="zone-page-summary"><div className={`zone-status-icon ${incidents.length ? 'attention' : ''}`}>{incidents.length ? <Activity size={23} /> : incidentsCursor ? <Clock3 size={23} /> : <Check size={23} />}</div><div><strong>{incidents.length ? 'Incidencias visibles en esta zona' : incidentsCursor ? 'Hay más información por revisar' : 'Sin incidencias visibles'}</strong><p>{incidents.length ? 'Estos casos están en evaluación o seguimiento. Una incidencia en evaluación aún no está confirmada.' : incidentsCursor ? 'La primera página no mostró incidencias activas. Continúa la consulta para revisar el resto.' : 'No aparecen incidencias activas en la consulta actual.'}</p></div></div>{incidents.length > 0 && <div className="incident-list">{incidents.map(incident => <div className="incident-row" key={incident.incident_id}><div><small>{incident.service === 'MOVIL' ? 'Telefonía móvil' : incident.service === 'INTERNET' ? 'Internet' : incident.service}</small><strong>Incidencia #{incident.incident_id.slice(0, 8)}</strong><span>Actualizado: {dateLabel(incident.updated_at)}</span></div><StatusBadge status={incident.status} /></div>)}</div>}{incidentsState === 'error' && incidents.length > 0 && <ErrorPanel error={incidentsError} compact onRetry={() => void loadIncidents(session.token, zoneId, incidentsCursor || undefined)} />}{incidentsCursor && <div className="load-more"><button className="outline-button" disabled={incidentsState === 'loading'} onClick={() => void loadIncidents(session.token, zoneId, incidentsCursor)}>{incidentsState === 'loading' && <LoaderCircle className="spin" size={16} />} Cargar más incidencias</button></div>}</>}</section><div className="azure-callout"><div className="azure-callout-icon"><RadioTower size={24} /></div><div><strong>Estado público de toda la red</strong><p>Azure mantiene una vista independiente con la última actualización conocida de cada zona. Comprueba allí la hora de sincronización.</p></div><a href={AZURE_STATUS_URL} target="_blank" rel="noopener noreferrer">Abrir estado público <ArrowUpRight size={17} /></a></div></>}
      </main><footer className="app-footer"><span>© 2026 Red TeleCorp · Centro de servicio</span><span>Portal de clientes · Datos de demostración</span></footer></div>
  </div>
}

function PlusSymbol() { return <span className="nav-plus">+</span> }

function ReportRow({ report, zones, onOpen }: { report: Report; zones: Zone[]; onOpen: () => void }) {
  return <button className="report-row" onClick={onOpen}><div className="report-row-icon"><FileText size={20} /></div><div className="report-row-info"><strong>{PROBLEM_OPTIONS.find(option => option.value === report.problem_type)?.label || report.problem_type || 'Reporte de servicio'}</strong><span>{zones.find(zone => zone.zone_id === report.zone_id)?.name || report.zone_id || 'Zona sin identificar'} <i /> {dateLabel(report.created_at)}</span></div><StatusBadge status={report.status} /><ChevronRight className="row-chevron" size={18} /></button>
}

export default App
