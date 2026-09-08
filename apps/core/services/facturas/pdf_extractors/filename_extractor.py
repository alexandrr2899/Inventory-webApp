"""filename_extractor — datos fiables tomados del NOMBRE del archivo.

Convenciones observadas:
  Factura: "Fact <NUM> <CLIENTE>"          -> "Fact 9543 Inversiones Zaga"
  Envío:   "<CLIENTE> Envio <PRODUCTO> <NUM>" -> "RENATO DIAZ Envio camiseta 126"
  Envío:   "<CLIENTE> <PRODUCTO> <NUM>"       -> "Antonio Sanchez camiseta 126"
  Envío:   "<CLIENTE> <NUM>"                  -> "Antonio Sanchez 126"
"""
import os
import re


# Se usa solo para separar el nombre del cliente del token de producto en el
# patrón "<CLIENTE> <PRODUCTO> <NUM>". La categoría se decide en invoice_service.
_PRODUCTOS = ('camiseta', 'lisa', 'otro')


def extraer_de_nombre(nombre_archivo):
    """Devuelve dict con las claves encontradas: numero_documento, producto,
    cliente_nombre, tipo_documento. Solo incluye las que detecta."""
    datos = {}
    if not nombre_archivo:
        return datos
    base = os.path.basename(str(nombre_archivo))
    base = re.sub(r'\.pdf$', '', base, flags=re.IGNORECASE).strip()

    # "Envio" es el separador fiable entre cliente y datos del documento.
    # Exigir límites de palabra evita detectar por accidente nombres que solo
    # contengan esas letras.
    es_envio = re.search(r'\benv[íi]o\b', base, re.IGNORECASE)
    es_factura = re.search(r'\bfact', base, re.IGNORECASE)

    if es_envio:
        datos['tipo_documento'] = 'envio'
        # Todo lo anterior a "Envio" es siempre el cliente. Lo posterior puede
        # ser producto + número, solo número o solo producto; no condicionamos
        # la lectura del cliente a que el nombre del archivo tenga número.
        cliente = base[:es_envio.start()].strip(' -_')
        if cliente:
            datos['cliente_nombre'] = cliente

        sufijo = base[es_envio.end():].strip()
        nums = re.findall(r'\d+', sufijo)
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
        # Sin palabra "Envio", aceptar el patrón común "<CLIENTE> <PRODUCTO> <NUM>".
        producto_pat = '|'.join(re.escape(p) for p in _PRODUCTOS)
        m = re.search(rf'(.+?)\s+({producto_pat})\s+(\d+)$', base, re.IGNORECASE)
        if m:
            cliente = m.group(1).strip()
            datos['tipo_documento'] = 'envio'
            if cliente:
                datos['cliente_nombre'] = cliente
            datos['numero_documento'] = m.group(3)
        else:
            # Si no dice "Fact", por convención no es factura: usar número final como envío.
            m = re.search(r'(.+?)\s+(\d+)$', base)
            if m:
                cliente = m.group(1).strip()
                datos['tipo_documento'] = 'envio'
                if cliente:
                    datos['cliente_nombre'] = cliente
                datos['numero_documento'] = m.group(2)
            else:
                nums = re.findall(r'\d+', base)
                if nums:
                    datos['tipo_documento'] = 'envio'
                    datos['numero_documento'] = nums[-1]

    return datos
