"""textnorm — Normalización de texto para comparar nombres.

Módulo hoja a propósito: no importa nada de Django ni del proyecto, así lo pueden
usar tanto `models.py` como los servicios sin ciclos de importación.
"""
import unicodedata


def norm(s):
    """Normaliza para comparar: minúsculas, sin acentos, espacios colapsados."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(s.lower().split())
