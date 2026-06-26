"""bulk_service — subida en bloque de PDFs con auto-emparejado de cliente.

Flujo en dos pasos:
  1) procesar_archivos(): guarda los PDFs en una carpeta temporal por lote, extrae
     datos de cada uno y propone un cliente emparejado por nombre. Devuelve filas
     para una tabla de revisión.
  2) crear_desde_lote(): a partir de las filas revisadas (cliente confirmado por el
     usuario), crea los DocumentoFactura y limpia los temporales.
"""
import os
import unicodedata
import uuid

from django.conf import settings
from django.core.files import File
from django.utils.text import get_valid_filename

from apps.core.models import Cliente
from . import invoice_service, pdf_service
from .pdf_extractors import filename_extractor
from .pdf_extractors.base_extractor import parse_decimal, parse_fecha


def _s(v):
    """Decimal/valor a string con punto decimal (evita la localización del template)."""
    return '' if v in (None, '') else str(v)

_LOTE_SUBDIR = os.path.join('facturas', '_lote')


def _lote_dir(batch_id):
    """Ruta absoluta de la carpeta temporal del lote (validada, sin traversal)."""
    batch_id = get_valid_filename(batch_id or '')
    base = os.path.realpath(os.path.join(settings.MEDIA_ROOT, _LOTE_SUBDIR))
    ruta = os.path.realpath(os.path.join(base, batch_id))
    if not batch_id or os.path.dirname(ruta) != base:
        raise ValueError('batch_id inválido')
    return ruta


def _archivo_en_lote(batch_id, nombre):
    """Ruta absoluta y segura de un archivo dentro del lote (sin traversal)."""
    carpeta = _lote_dir(batch_id)
    ruta = os.path.realpath(os.path.join(carpeta, os.path.basename(nombre)))
    if os.path.dirname(ruta) != carpeta:
        raise ValueError('nombre de archivo inválido')
    return ruta


def _norm(s):
    """Normaliza para comparar: minúsculas, sin acentos, espacios colapsados."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(s.lower().split())


def match_cliente(nombre, solo_exacto=False):
    """Empareja un nombre (del archivo) a un Cliente existente; None si no hay match.

    Comparación insensible a mayúsculas y acentos. Con ``solo_exacto=True`` solo
    acepta igualdad exacta normalizada (sin el fallback de 'contiene'); se usa en
    la ingesta automática, donde no hay revisión humana para corregir un mal match.
    """
    objetivo = _norm(nombre)
    if not objetivo:
        return None
    clientes = list(Cliente.objects.all())
    # 1) Igualdad exacta normalizada.
    for c in clientes:
        if _norm(c.nombre) == objetivo:
            return c
    if solo_exacto:
        return None
    # 2) 'Contiene' en cualquier dirección; preferir el nombre de cliente más largo.
    matches = [c for c in clientes
               if _norm(c.nombre) and (_norm(c.nombre) in objetivo or objetivo in _norm(c.nombre))]
    if matches:
        return max(matches, key=lambda c: len(c.nombre))
    return None


def procesar_archivos(archivos):
    """Guarda y procesa los PDFs subidos. Devuelve (batch_id, filas).

    Cada fila: dict con archivo, tipo, cliente_id, cliente_match (nombre sugerido),
    numero_documento, fecha_documento (iso o ''), producto, total_libras, subtotal,
    isv, monto_total.
    """
    batch_id = uuid.uuid4().hex
    carpeta = _lote_dir(batch_id)
    os.makedirs(carpeta, exist_ok=True)

    filas = []
    for archivo in archivos:
        nombre = get_valid_filename(os.path.basename(archivo.name))
        destino = os.path.join(carpeta, nombre)
        with open(destino, 'wb') as fh:
            for chunk in archivo.chunks():
                fh.write(chunk)

        # Extraer desde el archivo subido original (conserva .name para el extractor).
        tipo = invoice_service.detectar_tipo(archivo.name)
        archivo.seek(0)
        prev = invoice_service.previsualizar(tipo, archivo)
        datos = prev['datos']

        nombre_cli = filename_extractor.extraer_de_nombre(archivo.name).get('cliente_nombre', '')
        cliente = match_cliente(nombre_cli)

        fecha = datos.get('fecha_documento')
        filas.append({
            'archivo': nombre,
            'nombre_original': archivo.name,
            'tipo': tipo,
            'cliente_id': cliente.pk if cliente else '',
            'cliente_sugerido': nombre_cli,
            'numero_documento': datos.get('numero_documento', ''),
            'fecha_documento': fecha.isoformat() if fecha else '',
            'producto': datos.get('producto', ''),
            'total_libras': _s(datos.get('total_libras')),
            'subtotal': _s(datos.get('subtotal')),
            'isv': _s(datos.get('isv')),
            'monto_total': _s(datos.get('monto_total')),
        })
    return batch_id, filas


def crear_desde_lote(batch_id, filas):
    """Crea los documentos a partir de las filas revisadas. Limpia los temporales.

    `filas`: lista de dicts con al menos cliente_id, tipo, archivo y los campos
    extraídos (ya posiblemente editados por el usuario en la tabla de revisión).
    Devuelve (creados, errores) donde errores es lista de (archivo, motivo).
    """
    creados = 0
    errores = []
    for fila in filas:
        archivo_nombre = fila.get('archivo', '')
        try:
            cliente = Cliente.objects.get(pk=fila['cliente_id'])
        except (Cliente.DoesNotExist, ValueError, KeyError):
            errores.append((archivo_nombre, 'sin cliente'))
            continue
        try:
            ruta = _archivo_en_lote(batch_id, archivo_nombre)
        except ValueError:
            errores.append((archivo_nombre, 'archivo inválido'))
            continue
        if not os.path.exists(ruta):
            errores.append((archivo_nombre, 'archivo no encontrado'))
            continue

        # Coercionar los valores del formulario a los tipos correctos.
        datos = {}
        if fila.get('numero_documento'):
            datos['numero_documento'] = fila['numero_documento']
        if fila.get('producto'):
            datos['producto'] = fila['producto']
        fecha = parse_fecha(fila.get('fecha_documento'))
        if fecha:
            datos['fecha_documento'] = fecha
        for campo in ('total_libras', 'subtotal', 'isv', 'monto_total'):
            d = parse_decimal(fila.get(campo))
            if d is not None:
                datos[campo] = d

        with open(ruta, 'rb') as fh:
            texto = pdf_service.extraer_texto(fh)
            fh.seek(0)
            invoice_service.crear_documento(
                cliente=cliente, tipo_documento=fila.get('tipo') or 'factura',
                archivo=File(fh, name=archivo_nombre),
                producto=fila.get('producto') or None,
                datos=datos, texto_extraido=texto,
            )
        creados += 1
        try:
            os.remove(ruta)
        except OSError:
            pass

    # Intentar limpiar la carpeta del lote si quedó vacía.
    try:
        os.rmdir(_lote_dir(batch_id))
    except OSError:
        pass
    return creados, errores
