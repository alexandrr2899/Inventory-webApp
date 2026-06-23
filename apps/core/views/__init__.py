"""
Paquete de vistas de core, dividido en módulos temáticos.

- common / stock / calc / payloads: helpers compartidos (barrel con `import *`).
- dashboard, inventario, movimientos, conteos, catalogos, reportes,
  notificaciones, api, produccion, admin_ops: vistas por dominio.

Este __init__ re-exporta todo para que `from . import views` + `views.<nombre>`
(urls.py) y los imports de tests sigan funcionando.
"""

# ── Helpers compartidos (incluyen helpers _ vía barrel) ──────────────────────
from .common import *    # noqa: F401,F403
from .stock import *     # noqa: F401,F403
from .calc import *      # noqa: F401,F403
from .payloads import *  # noqa: F401,F403

# ── Módulos de vistas (nombres públicos usados por urls.py) ──────────────────
from .dashboard import *      # noqa: F401,F403
from .inventario import *     # noqa: F401,F403
from .movimientos import *    # noqa: F401,F403
from .conteos import *        # noqa: F401,F403
from .catalogos import *      # noqa: F401,F403
from .reportes import *       # noqa: F401,F403
from .notificaciones import * # noqa: F401,F403
from .api import *            # noqa: F401,F403
from .produccion import *     # noqa: F401,F403
from .admin_ops import *      # noqa: F401,F403
from .facturas import *       # noqa: F401,F403
from .facturas_pagos import * # noqa: F401,F403

# ── Helpers con prefijo _ usados por código externo (tests) ──────────────────
from .calc import _calcular_tramos                       # noqa: F401
from .payloads import _payload_produccion_dia            # noqa: F401
from .stock import _aplicar_efecto_detalle, _stock_en_momento  # noqa: F401
