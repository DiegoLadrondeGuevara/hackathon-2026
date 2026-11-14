"""Reglas de negocio puras (sin AWS). Se usan desde las Lambdas; no se reescriben."""
from decimal import Decimal

# --- Antenas (enunciado) ---
DOWN_BELOW = 60          # < 60 GB/min: caída
SATURATED_ABOVE = 129    # > 129 GB/min: saturada
NORMALS_TO_CLOSE = 5     # lecturas normales seguidas que cierran un episodio
RECURRENCE_EPISODES = 3  # episodios en la ventana que marcan recurrencia
RECURRENCE_DAYS = 7

# --- Incidente colectivo (enunciado) ---
COLLECTIVE_USERS = 10
COLLECTIVE_WINDOW_HOURS = 24
THRESHOLDS_USERS = (100, 1000)  # cruces que reevalúan prioridad (change=THRESHOLD)

ANTENNA_SEVERITY = {"NORMAL": 0, "SATURADA": 1, "CAIDA": 2, "INHABILITADA": 3}

REPORT_TRANSITIONS = {
    "REGISTRADA": {"EN_REVISION"},
    "EN_REVISION": {"EN_ATENCION"},
    "EN_ATENCION": {"SOLUCIONADA"},
    "SOLUCIONADA": {"CERRADA", "EN_ATENCION"},
    "CERRADA": set(),
}

INCIDENT_TRANSITIONS = {
    "EVALUACION": {"CONFIRMADO", "CERRADO"},
    "CONFIRMADO": {"RESTABLECIDO"},
    "RESTABLECIDO": {"CERRADO", "CONFIRMADO"},
    "CERRADO": set(),
}
MILESTONES = ("EVALUACION", "CONFIRMADO", "RESTABLECIDO")

ZONE_CRITICALITY = {"RESIDENCIAL": 1, "INDUSTRIAL": 2, "EDUCATIVA": 3, "MEDICA": 4, "CRITICA": 5}


def classify_gb(gb) -> str:
    """0 -> INHABILITADA; < 60 -> CAIDA; > 129 -> SATURADA; en otro caso NORMAL."""
    value = Decimal(str(gb))
    if value < 0:
        raise ValueError("gb_per_min no puede ser negativo")
    if value == 0:
        return "INHABILITADA"
    if value < DOWN_BELOW:
        return "CAIDA"
    if value > SATURATED_ABOVE:
        return "SATURADA"
    return "NORMAL"


def worse(state_a: str, state_b: str) -> str:
    return state_a if ANTENNA_SEVERITY[state_a] >= ANTENNA_SEVERITY[state_b] else state_b


def can_transition_report(current: str, target: str) -> bool:
    return target in REPORT_TRANSITIONS.get(current, set())


def can_transition_incident(current: str, target: str) -> bool:
    return target in INCIDENT_TRANSITIONS.get(current, set())


def users_points(affected_users: int) -> int:
    if affected_users >= 1000:
        return 3
    if affected_users >= 100:
        return 2
    if affected_users >= COLLECTIVE_USERS:
        return 1
    return 0


def priority(affected_users: int, criticality: int, worst_antenna_state: str | None = None):
    """Devuelve (score, nivel). score = 2*puntos_usuarios + 2*puntos_severidad + criticidad de la zona.
    Nivel: P1 si score >= 11, P2 si >= 7, P3 en otro caso. Valores iniciales, ajustables aquí."""
    severity = ANTENNA_SEVERITY.get(worst_antenna_state or "NORMAL", 0)
    score = 2 * users_points(affected_users) + 2 * severity + criticality
    level = "P1" if score >= 11 else "P2" if score >= 7 else "P3"
    return score, level
