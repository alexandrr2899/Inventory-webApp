"""envio_extractor — datos de un Envío desde texto posicional."""
import re
from decimal import Decimal
from .base_extractor import BaseExtractor, parse_fecha


_FECHA_RE = re.compile(r'\d{2}/\d{2}/\d{4}')
_ENTERO_RE = re.compile(r'(?<![\d/.,\-])\d+(?![\d/.,\-])')


class EnvioExtractor(BaseExtractor):
    def extraer(self, texto):
        datos = {}
        texto = texto or ''

        mf = _FECHA_RE.search(texto)
        if mf:
            f = parse_fecha(mf.group(0))
            if f:
                datos['fecha_documento'] = f

        enteros = sorted({int(x) for x in _ENTERO_RE.findall(texto)}, reverse=True)
        if enteros:
            datos['_enteros'] = enteros          # auxiliar para invoice_service
            datos['total_libras'] = Decimal(enteros[0])

        return datos
