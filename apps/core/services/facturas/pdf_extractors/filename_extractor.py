"""filename_extractor — datos fiables tomados del NOMBRE del archivo.

Convenciones observadas:
  Factura: "Fact <NUM> <CLIENTE>"          -> "Fact 9543 Inversiones Zaga"
  Envío:   "<CLIENTE> Envio <PRODUCTO> <NUM>" -> "RENATO DIAZ Envio camiseta 126"
"""
import os
import re


_PRODUCTOS = ('camiseta', 'lisa', 'otro')


def _normaliza_producto(token):
    t = (token or '').strip().lower()
    return t if t in _PRODUCTOS else ''


def extraer_de_nombre(nombre_archivo):
    """Devuelve dict con las claves encontradas: numero_documento, producto,
    cliente_nombre, tipo_documento. Solo incluye las que detecta."""
    datos = {}
    if not nombre_archivo:
        return datos
    base = os.path.basename(str(nombre_archivo))
    base = re.sub(r'\.pdf$', '', base, flags=re.IGNORECASE).strip()

    es_envio = re.search(r'env[íi]o', base, re.IGNORECASE)
    es_factura = re.search(r'\bfact', base, re.IGNORECASE)

    if es_envio:
        datos['tipo_documento'] = 'envio'
        # "<CLIENTE> Envio <PRODUCTO> <NUM>"
        m = re.search(r'(.+?)\s+env[íi]o\s+([A-Za-zÁÉÍÓÚáéíóúÑñ]+)\s+(\d+)', base, re.IGNORECASE)
        if m:
            cliente = m.group(1).strip()
            prod = _normaliza_producto(m.group(2))
            if cliente:
                datos['cliente_nombre'] = cliente
            if prod:
                datos['producto'] = prod
            datos['numero_documento'] = m.group(3)
        else:
            # fallback: último número del nombre
            nums = re.findall(r'\d+', base)
            if nums:
                datos['numero_documento'] = nums[-1]
    elif es_factura:
        datos['tipo_documento'] = 'factura'
        # "Fact <NUM> <CLIENTE>"
        m = re.search(r'fact\w*\s+(\d+)\s+(.+)', base, re.IGNORECASE)
        if m:
            datos['numero_documento'] = m.group(1)
            cliente = m.group(2).strip()
            if cliente:
                datos['cliente_nombre'] = cliente
        else:
            nums = re.findall(r'\d+', base)
            if nums:
                datos['numero_documento'] = nums[0]
    else:
        # sin pista de tipo: tomar el primer número si lo hay
        nums = re.findall(r'\d+', base)
        if nums:
            datos['numero_documento'] = nums[0]
    return datos
