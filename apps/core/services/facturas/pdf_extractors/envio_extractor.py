"""envio_extractor — datos de un Envío desde texto posicional."""
import re
from decimal import Decimal
from .base_extractor import BaseExtractor, extraer_fecha, quitar_fechas


_ENTERO_RE = re.compile(r'(?<![\d/.,\-])\d+(?![\d/.,\-])')


class EnvioExtractor(BaseExtractor):
    def extraer(self, texto):
        datos = {}
        texto = texto or ''

        fecha = extraer_fecha(texto)
        if fecha:
            datos['fecha_documento'] = fecha

        texto_sin_fechas = quitar_fechas(texto)
        enteros = sorted({int(x) for x in _ENTERO_RE.findall(texto_sin_fechas)}, reverse=True)
        if enteros:
            datos['_enteros'] = enteros          # auxiliar para invoice_service
            datos['total_libras'] = Decimal(enteros[0])

        return datos
