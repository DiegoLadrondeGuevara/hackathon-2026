"use strict";

// Catálogo fijo de la demo; debe coincidir con ZONES en scripts/seed.py de AWS.
// La API pública de Azure solo recibe zone_id y estados, sin nombres ni datos personales.
const ZONE_CATALOG = [
  ["Z01", "Miraflores"], ["Z02", "San Isidro"], ["Z03", "Santiago de Surco"],
  ["Z04", "San Borja"], ["Z05", "La Molina"], ["Z06", "Callao"],
  ["Z07", "Ate"], ["Z08", "San Miguel"], ["Z09", "Jesús María"],
  ["Z10", "San Juan de Lurigancho"], ["Z11", "Villa El Salvador"], ["Z12", "Barranco"],
];

const STATUS = {
  EVALUACION: { badge: "En evaluación", description: "Estamos comprobando una posible afectación.", tone: "evaluating", kind: "attention", rank: 1 },
  CONFIRMADO: { badge: "Incidencia confirmada", description: "El equipo trabaja en una afectación identificada.", tone: "confirmed", kind: "attention", rank: 0 },
  RESTABLECIDO: { badge: "Servicio restablecido", description: "El servicio se recuperó y continúa en seguimiento.", tone: "restored", kind: "attention", rank: 2 },
  SIN_INCIDENTE: { badge: "Sin alerta publicada", description: "El último evento recibido indicó un cierre.", tone: "clear", kind: "clear", rank: 5 },
};

const STALE_AFTER_MS = 10 * 60 * 1000;
const REFRESH_MS = 30 * 1000;
const apiBase = String(window.RED_TELECORP_API_BASE_URL || "").replace(/\/$/, "");
const elements = {
  notice: document.getElementById("notice"),
  zones: document.getElementById("zones"),
  search: document.getElementById("zone-search"),
  filter: document.getElementById("status-filter"),
  refresh: document.getElementById("refresh-button"),
  resultCount: document.getElementById("result-count"),
  lastChecked: document.getElementById("last-checked"),
  attention: document.getElementById("count-attention"),
  clear: document.getElementById("count-clear"),
  pending: document.getElementById("count-pending"),
};

let publishedRows = [];
let checkedAt = null;
let requestFailed = false;
let loading = false;

function add(parent, tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value != null) element.textContent = value;
  parent.appendChild(element);
  return element;
}

function formattedTime(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Fecha no disponible";
  return date.toLocaleString("es-PE", { dateStyle: "medium", timeStyle: "short" });
}

function ageLabel(value) {
  const age = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(age) || age < 0) return "Fecha no disponible";
  if (age < 60_000) return "hace menos de un minuto";
  if (age < 3_600_000) return `hace ${Math.floor(age / 60_000)} min`;
  if (age < 86_400_000) return `hace ${Math.floor(age / 3_600_000)} h`;
  return `hace ${Math.floor(age / 86_400_000)} días`;
}

function stateFor(row) {
  if (!row) return {
    badge: "Sin información publicada", description: "Aún no recibimos un estado para esta zona.",
    tone: "pending", kind: "pending", rank: 4,
  };
  const known = STATUS[row.status];
  if (!known) return {
    badge: "Estado por confirmar", description: "La última publicación no tiene un estado reconocido.",
    tone: "pending", kind: "pending", rank: 3,
  };
  const receivedAt = new Date(row.last_synced_at).getTime();
  if (!Number.isFinite(receivedAt) || Date.now() - receivedAt > STALE_AFTER_MS || receivedAt > Date.now() + 60_000) {
    return {
      badge: "Información por actualizar",
      description: `Último estado recibido: ${known.badge.toLowerCase()}. No lo mostramos como estado actual.`,
      tone: "pending", kind: "pending", rank: 3,
    };
  }
  return known;
}

function catalogWithRows() {
  const byId = new Map();
  for (const row of publishedRows) {
    if (row && typeof row.zone_id === "string" && row.zone_id) byId.set(row.zone_id, row);
  }
  const catalogIds = new Set(ZONE_CATALOG.map(([id]) => id));
  const catalog = ZONE_CATALOG.map(([id, name]) => ({ id, name, row: byId.get(id) }));
  for (const [id, row] of byId) {
    if (!catalogIds.has(id)) catalog.push({ id, name: `Zona ${id} · nombre pendiente`, row });
  }
  return catalog.map(zone => ({ ...zone, state: stateFor(zone.row) }));
}

function createCard(zone) {
  const card = document.createElement("article");
  card.className = `zone-card ${zone.state.kind} ${zone.state.tone}`;
  const heading = add(card, "div", "zone-head");
  const headingText = add(heading, "div");
  add(headingText, "h3", "zone-name", zone.name);
  add(headingText, "span", "zone-id", `ZONA ${zone.id}`);
  add(card, "span", `zone-badge ${zone.state.tone}`, zone.state.badge);
  add(card, "p", "zone-description", zone.state.description);
  if (zone.row) {
    add(card, "p", "zone-last", `Recibido en Azure: ${formattedTime(zone.row.last_synced_at)}`);
  } else {
    add(card, "p", "zone-last", "No hay una publicación anterior.");
  }
  const meta = add(card, "div", "zone-meta");
  add(meta, "span", "", zone.row ? ageLabel(zone.row.last_synced_at) : "Publicación pendiente");
  if (zone.state.kind === "attention" && /^P[123]$/.test(zone.row?.priority || "")) {
    add(meta, "strong", "", `Prioridad ${zone.row.priority}`);
  }
  return card;
}

function render() {
  const all = catalogWithRows();
  const counts = { attention: 0, clear: 0, pending: 0 };
  for (const zone of all) counts[zone.state.kind]++;
  if (checkedAt) {
    elements.attention.textContent = String(counts.attention);
    elements.clear.textContent = String(counts.clear);
    elements.pending.textContent = String(counts.pending);
    elements.lastChecked.textContent = formattedTime(checkedAt);
  }

  const term = elements.search.value.trim().toLocaleLowerCase("es-PE");
  const filter = elements.filter.value;
  const visible = all
    .filter(zone => (filter === "all" || zone.state.kind === filter) &&
      (!term || `${zone.name} ${zone.id}`.toLocaleLowerCase("es-PE").includes(term)))
    .sort((a, b) => a.state.rank - b.state.rank || a.name.localeCompare(b.name, "es-PE"));

  elements.zones.replaceChildren();
  for (const zone of visible) elements.zones.appendChild(createCard(zone));
  if (!visible.length) add(elements.zones, "p", "zone-empty", "No encontramos zonas con ese filtro. Prueba otro nombre o estado.");
  elements.resultCount.textContent = `${visible.length} de ${all.length} zonas visibles`;

  if (loading && !checkedAt) {
    elements.notice.className = "notice loading";
    elements.notice.textContent = "Consultando las zonas publicadas…";
  } else if (requestFailed) {
    elements.notice.className = "notice error";
    elements.notice.textContent = checkedAt
      ? `No pudimos actualizar la consulta. Se muestra lo recibido por última vez el ${formattedTime(checkedAt)}.`
      : "No pudimos consultar la API. Las zonas se muestran sin estado hasta recuperar la conexión.";
  } else if (counts.pending) {
    elements.notice.className = "notice warning";
    elements.notice.textContent = `${counts.pending} ${counts.pending === 1 ? "zona tiene" : "zonas tienen"} información sin publicar o atrasada. Su último estado no debe interpretarse como actual.`;
  } else {
    elements.notice.className = "notice";
    elements.notice.textContent = "La información publicada de todas las zonas está al día según las últimas sincronizaciones recibidas.";
  }
}

async function refresh() {
  if (loading) return;
  loading = true;
  elements.refresh.disabled = true;
  render();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12_000);
  try {
    if (!apiBase || apiBase.includes("REPLACE_ME")) throw new Error("API sin configurar");
    const response = await fetch(`${apiBase}/api/estado`, { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    if (!Array.isArray(body.zones)) throw new Error("Respuesta inválida");
    publishedRows = body.zones;
    checkedAt = new Date();
    requestFailed = false;
  } catch {
    requestFailed = true;
  } finally {
    clearTimeout(timeout);
    loading = false;
    elements.refresh.disabled = false;
    render();
  }
}

elements.search.addEventListener("input", render);
elements.filter.addEventListener("change", render);
elements.refresh.addEventListener("click", refresh);
refresh();
setInterval(refresh, REFRESH_MS);
