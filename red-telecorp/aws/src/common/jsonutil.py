"""JSON que tolera Decimal (DynamoDB) y conjuntos."""
import json
from decimal import Decimal


def _default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"No serializable: {type(obj)}")


def dumps(obj) -> str:
    return json.dumps(obj, default=_default, separators=(",", ":"), ensure_ascii=False)
