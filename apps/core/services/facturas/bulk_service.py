"""bulk_service — subida en bloque de PDFs con auto-emparejado de cliente.

Flujo en dos pasos:
  1) procesar_archivos(): guarda los PDFs en una carpeta temporal por lote, extrae
     datos de cada uno y propone un cliente emparejado por nombre. Devuelve filas
     para una tabla de revisión.
  2) crear_desde_lote(): a partir de las filas revisadas (cliente confirmado por el
     usuario), crea los DocumentoFactura y limpia los temporales.
"""
import os
import uuid

from django.conf import settings
from django.core.files import File
from django.core.exceptions import ValidationError
from django.utils.text import get_valid_filename

from apps.core.models import Cliente, CategoriaProducto, ClienteAlias
from apps.core.forms import validar_upload, MAX_PDF_MB
from apps.core.textnorm import norm as _norm
from . import invoice_service, pdf_service, payment_service
from .pdf_extractors import filename_extractor
from .pdf_extractors.base_extractor import parse_decimal, parse_fecha


def _s(v):
    """Decimal/valor a string con punto decimal (evita la localización del template)."""
    return '' if v in (None, '') else str(v)

_LOTE_SUBDIR = os.path.join('facturas', '_lote')
MAX_ARCHIVOS_LOTE = 50


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


def match_cliente(nombre, solo_exacto=False):
    """Empareja un nombre (del archivo) a un Cliente existente; None si no hay match.

    Orden: 1) nombre exacto normalizado, 2) alias exacto normalizado,
    3) 'contiene' en cualquier dirección (solo si no `solo_exacto`).

    El alias va después del nombre real para que nunca pueda tapar a un cliente
    existente, y antes del 'contiene' porque un alias es una afirmación explícita
    del usuario mientras que el 'contiene' es una corazonada. Como el paso 2 es
    igualdad exacta, es tan confiable como el 1: por eso la ingesta automática
    (`solo_exacto=True`, sin revisión humana que corrija un mal match) también
    empareja por alias.
    """
    objetivo = _norm(nombre)
    if not objetivo:
        return None
    clientes_todos = list(Cliente.objects.all())
    # 1) Igualdad exacta normalizada del nombre.
    for c in clientes_todos:
        if _norm(c.nombre) == objetivo:
            return c
    # 2) Alias exacto. Una consulta indexada, no todos los alias en memoria.
    alias = ClienteAlias.objects.filter(
        alias_norm=objetivo).select_related('cliente').first()
    if alias:
        return alias.cliente
    if solo_exacto:
        return None
    # 3) 'Contiene' en cualquier dirección; preferir el nombre de cliente más largo.
    matches = [c for c in clientes_todos
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
    archivos = list(archivos)
    if len(archivos) > MAX_ARCHIVOS_LOTE:
        raise ValidationError(f'El lote no puede superar {MAX_ARCHIVOS_LOTE} archivos.')

    for archivo in archivos:
        validar_upload(archivo, extensiones=['.pdf'], max_mb=MAX_PDF_MB, magic=b'%PDF')

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
            'categoria_id': datos.get('categoria_id', ''),
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
        categoria = None
        if fila.get('categoria_id'):
            categoria = CategoriaProducto.objects.filter(pk=fila['categoria_id']).first()
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
            doc = invoice_service.crear_documento(
                cliente=cliente, tipo_documento=fila.get('tipo') or 'factura',
                archivo=File(fh, name=archivo_nombre),
                categoria=categoria,
                datos=datos, texto_extraido=texto,
            )
        payment_service.aplicar_saldo_a_favor(doc)
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
