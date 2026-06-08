"""
Paquete de vistas de core.

Durante el refactor incremental, todo el código vive en `main.py` y este
__init__ lo re-exporta para que `from . import views` + `views.<algo>` y los
imports existentes (urls, tests) sigan funcionando sin cambios.

A medida que se extraigan módulos (stock, conteos, reportes, etc.), se irán
agregando aquí sus re-exports y achicando main.py.
"""

# Helpers compartidos (incluye barrel con helpers _ y re-exports de Django/modelos)
from .common import *    # noqa: F401,F403
from .stock import *     # noqa: F401,F403
from .calc import *      # noqa: F401,F403
from .payloads import *  # noqa: F401,F403

# Nombres públicos (vistas) — usados por urls.py vía views.<nombre>
from .main import *         # noqa: F401,F403
from .inventario import *   # noqa: F401,F403
from .movimientos import *  # noqa: F401,F403
from .conteos import *      # noqa: F401,F403
from .reportes import *     # noqa: F401,F403

# Helpers con prefijo _ usados por código externo (tests) — import * no los trae
from .calc import _calcular_tramos  # noqa: F401
from .payloads import _payload_produccion_dia  # noqa: F401
from .stock import _aplicar_efecto_detalle, _stock_en_momento  # noqa: F401
