"""envio_extractor — extrae datos de un Envío desde texto plano."""
from .base_extractor import BaseExtractor, parse_decimal, parse_fecha


class EnvioExtractor(BaseExtractor):
    def extraer(self, texto):
        datos = {}

        numero = self._buscar(r'Env[íi]o\s+(?:No\.?|N[º°]\.?|#)\s*[:]?\s*([A-Z0-9][A-Z0-9\-]+)', texto)
        if numero:
            datos['numero_documento'] = numero

        fecha = parse_fecha(self._buscar(r'Fecha\s*[:]?\s*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})', texto))
        if fecha:
            datos['fecha_documento'] = fecha

        cliente = self._buscar(r'Cliente\s*[:]?\s*(.+)', texto)
        if cliente:
            datos['cliente'] = cliente

        producto = self._buscar(r'Producto\s*[:]?\s*(Camiseta|Lisa|Otro)', texto)
        if producto:
            datos['producto'] = producto.lower()

        libras = parse_decimal(self._buscar(r'(?:Total\s*)?Libras\s*[:]?\s*([\d.,]+)', texto))
        if libras is not None:
            datos['total_libras'] = libras

        return datos
