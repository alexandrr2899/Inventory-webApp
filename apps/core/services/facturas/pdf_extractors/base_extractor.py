"""base_extractor — interfaz y helpers de parseo para extractores de PDF."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


_FECHA_EN_TEXTO_RE = re.compile(
    r'(?<!\d)(\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{2,4})(?!\d)'
)


def parse_decimal(texto):
    """Convierte 'L 1,150.00' / '1150.00' → Decimal; None si no se puede."""
    if texto is None:
        return None
    limpio = re.sub(r'[^\d.,-]', '', str(texto))
    if not limpio:
        return None
    # Asume formato es-HN: ',' miles y '.' decimales.
    limpio = limpio.replace(',', '')
    try:
        return Decimal(limpio)
    except (InvalidOperation, ValueError):
        return None


def parse_fecha(texto):
    """Convierte una fecha en varios formatos comunes → date; None si falla."""
    if not texto:
        return None
    texto = str(texto).strip()
    # PyMuPDF puede insertar espacios o saltos de línea alrededor de los
    # separadores aunque la fecha se vea continua en el PDF.
    texto = re.sub(r'\s*([/.-])\s*', r'\1', texto)
    formatos = (
        '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y',
        '%Y-%m-%d', '%Y/%m/%d', '%d/%m/%y',
    )
    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def extraer_fecha(texto):
    """Devuelve la primera fecha calendario encontrada en texto de un PDF.

    Tolera los espacios y saltos que puede introducir el extractor de texto,
    además de días/meses con o sin cero inicial.
    """
    for coincidencia in _FECHA_EN_TEXTO_RE.finditer(texto or ''):
        fecha = parse_fecha(coincidencia.group(1))
        if fecha:
            return fecha
    return None


def quitar_fechas(texto):
    """Quita fechas para que sus números no contaminen otras heurísticas."""
    return _FECHA_EN_TEXTO_RE.sub(' ', texto or '')


class BaseExtractor:
    """Interfaz de extractor. Subclases implementan extraer(texto) -> dict."""

    def extraer(self, texto):
        raise NotImplementedError

    @staticmethod
    def _buscar(patron, texto, grupo=1, flags=re.IGNORECASE):
        m = re.search(patron, texto, flags)
        return m.group(grupo).strip() if m else None
