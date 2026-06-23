"""factura_extractor — extrae datos de una Factura desde texto plano."""
from .base_extractor import BaseExtractor, parse_decimal, parse_fecha


class FacturaExtractor(BaseExtractor):
    def extraer(self, texto):
        datos = {}

        numero = self._buscar(r'Factura\s*(?:No\.?|N[º°]\.?|#)?\s*[:]?\s*([A-Z0-9\-]+)', texto)
        if numero:
            datos['numero_documento'] = numero

        fecha = parse_fecha(self._buscar(r'Fecha\s*[:]?\s*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})', texto))
        if fecha:
            datos['fecha_documento'] = fecha

        cliente = self._buscar(r'Cliente\s*[:]?\s*(.+)', texto)
        if cliente:
            datos['cliente'] = cliente

        subtotal = parse_decimal(self._buscar(r'Subtotal\s*[:]?\s*([L$\s\d.,]+)', texto))
        if subtotal is not None:
            datos['subtotal'] = subtotal

        isv = parse_decimal(self._buscar(r'ISV[^:\n]*[:]?\s*([L$\s\d.,]+)', texto))
        if isv is not None:
            datos['isv'] = isv

        total = parse_decimal(self._buscar(r'(?<!Sub)Total\s*[:]?\s*([L$\s\d.,]+)', texto))
        if total is not None:
            datos['monto_total'] = total

        return datos
