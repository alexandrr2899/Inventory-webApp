"""
Paquete de vistas de core.

Durante el refactor incremental, todo el código vive en `main.py` y este
__init__ lo re-exporta para que `from . import views` + `views.<algo>` y los
imports existentes (urls, tests) sigan funcionando sin cambios.

A medida que se extraigan módulos (stock, conteos, reportes, etc.), se irán
agregando aquí sus re-exports y achicando main.py.
"""

# Nombres públicos (vistas) — usados por urls.py vía views.<nombre>
from .main import *  # noqa: F401,F403

# Helpers con prefijo _ usados por código externo (tests) — import * no los trae
from .main import (  # noqa: F401
    _calcular_tramos,
    _payload_produccion_dia,
    _aplicar_efecto_detalle,
    _stock_en_momento,
)
