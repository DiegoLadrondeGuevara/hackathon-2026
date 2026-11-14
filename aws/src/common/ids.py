"""IDs (ULID) y fechas ISO-8601 UTC con milisegundos."""
import os
import time
from datetime import UTC, datetime, timedelta

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_FMT_TAIL = "Z"


def new_id() -> str:
    """ULID: 48 bits de tiempo (ms) + 80 bits aleatorios, 26 caracteres ordenables."""
    n = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[n & 31])
        n >>= 5
    return "".join(reversed(chars))


def now_iso() -> str:
    return to_iso(datetime.now(UTC))


def to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", _FMT_TAIL)


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def shift_iso(value: str, **delta) -> str:
    """Suma (o resta con valores negativos) a una fecha ISO: shift_iso(t, hours=-24)."""
    return to_iso(parse_iso(value) + timedelta(**delta))


def epoch(value: str) -> int:
    return int(parse_iso(value).timestamp())
