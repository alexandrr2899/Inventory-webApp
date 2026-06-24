"""factura_extractor — datos de una Factura desde texto posicional."""
import re
from decimal import Decimal
from .base_extractor import BaseExtractor, parse_decimal, parse_fecha


_MONTO_RE = re.compile(r'\d{1,3}(?:,\d{3})*\.\d{2}')
_FECHA_RE = re.compile(r'\d{2}/\d{2}/\d{4}')


class FacturaExtractor(BaseExtractor):
    def extraer(self, texto):
        datos = {}

        mf = _FECHA_RE.search(texto or '')
        if mf:
            f = parse_fecha(mf.group(0))
            if f:
                datos['fecha_documento'] = f

        montos = []
        for s in _MONTO_RE.findall(texto or ''):
            d = parse_decimal(s)
            if d is not None and d not in montos:
                montos.append(d)

        if montos:
            total = max(montos)
            datos['monto_total'] = total
            resto = [m for m in montos if m != total]
            par = None
            for i in range(len(resto)):
                for j in range(i, len(resto)):
                    if resto[i] + resto[j] == total:
                        par = (resto[i], resto[j])
                        break
                if par:
                    break
            if par:
                datos['subtotal'] = max(par)
                datos['isv'] = min(par)

        return datos
