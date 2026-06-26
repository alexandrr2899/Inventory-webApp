"""base_extractor — interfaz y helpers de parseo para extractores de PDF."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


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
    formatos = ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%y')
    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


class BaseExtractor:
    """Interfaz de extractor. Subclases implementan extraer(texto) -> dict."""

    def extraer(self, texto):
        raise NotImplementedError

    @staticmethod
    def _buscar(patron, texto, grupo=1, flags=re.IGNORECASE):
        m = re.search(patron, texto, flags)
        return m.group(grupo).strip() if m else None
