"""Los handlers se despliegan como src/handlers/<archivo>.handler.
Este archivo agrega src/ al path para que `from common import ...` funcione dentro de Lambda."""
import os
import sys

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
