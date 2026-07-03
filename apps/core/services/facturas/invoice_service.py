"""invoice_service — alta de documentos (Factura/Envío) desde PDF o datos."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction

from apps.core.models import DocumentoFactura, TarifaCliente, CategoriaProducto
from . import pdf_service, status_service
from .pdf_extractors import filename_extractor


# Campos que un extractor puede aportar y que se copian directo al documento.
_CAMPOS_DIRECTOS = (
    'numero_documento', 'fecha_documento', 'fecha_vencimiento', 'subtotal', 'isv',
    'monto_total', 'total_libras',
)


def clasificar_categoria(haystack, con_predeterminada=True):
    """Primera categoría activa cuya palabra_clave aparece en haystack (case-insensitive).

    palabra_clave puede contener varias palabras separadas por coma: cualquiera que coincida cuenta.
    Si ninguna categoría coincide: devuelve predeterminada() si con_predeterminada=True, else None.
    """
    texto = (haystack or '').lower()
    for cat in CategoriaProducto.objects.filter(activa=True).order_by('orden', 'nombre'):
        kw = (cat.palabra_clave or '').strip()
        if kw and any(p.strip().lower() in texto for p in kw.split(',')):
            return cat
    return CategoriaProducto.predeterminada() if con_predeterminada else None


def detectar_tipo(nombre_archivo, default='factura'):
    """Detecta 'factura'/'envio' a partir del nombre del archivo; default si no se puede."""
    datos = filename_extractor.extraer_de_nombre(nombre_archivo or '')
    return datos.get('tipo_documento', default)


def previsualizar(tipo_documento, archivo):
    """Extrae texto y datos del PDF sin guardar nada.

    Usa un enfoque híbrido: nombre del archivo para numero/tipo/producto/cliente_nombre;
    texto del PDF para fecha, montos y libras.
    """
    texto = pdf_service.extraer_texto(archivo)
    datos_texto = pdf_service.get_extractor(tipo_documento).extraer(texto)

    nombre = getattr(archivo, 'name', '') or ''
    datos_nombre = filename_extractor.extraer_de_nombre(nombre)

    datos = dict(datos_nombre)          # base: lo fiable del nombre (numero, producto, cliente_nombre)
    for k, v in datos_texto.items():
        if k == '_enteros':
            continue
        # el texto manda para fecha/subtotal/isv/monto_total; para numero NO sobreescribe el del nombre
        if k == 'numero_documento' and datos.get('numero_documento'):
            continue
        datos[k] = v

    # Envío: corregir total_libras si el mayor entero es en realidad el número del documento
    if tipo_documento == 'envio':
        enteros = datos_texto.get('_enteros') or []
        numero = datos.get('numero_documento')
        if enteros and numero and str(enteros[0]) == str(numero) and len(enteros) > 1:
            datos['total_libras'] = Decimal(enteros[1])

    # Sugerir categoría para preseleccionar al revisar (factura: solo si hay coincidencia).
    haystack = nombre + '\n' + texto
    if tipo_documento == 'envio':
        cat = clasificar_categoria(haystack)
        if cat is not None:
            datos['categoria_id'] = cat.pk
    elif tipo_documento == 'factura':
        cat = clasificar_categoria(haystack, con_predeterminada=False)
        if cat is not None:
            datos['categoria_id'] = cat.pk

    datos.pop('_enteros', None)
    return {'texto_extraido': texto, 'datos': datos}


@transaction.atomic
def crear_documento(*, cliente, tipo_documento, archivo=None, categoria=None,
                    datos=None, texto_extraido=''):
    """Crea un DocumentoFactura. Para envío aplica tarifa activa (snapshot)."""
    datos = dict(datos or {})

    doc = DocumentoFactura(
        cliente=cliente,
        tipo_documento=tipo_documento,
        texto_extraido=texto_extraido,
        estado_revision='pendiente',
    )
    if archivo is not None:
        doc.archivo_pdf = archivo

    for campo in _CAMPOS_DIRECTOS:
        if campo in datos and datos[campo] is not None:
            setattr(doc, campo, datos[campo])

    # Vencimiento automático: fecha del documento + días de crédito del cliente
    # (solo si no vino un vencimiento explícito en los datos).
    if not doc.fecha_vencimiento and doc.fecha_documento and cliente.dias_credito:
        doc.fecha_vencimiento = doc.fecha_documento + timedelta(days=cliente.dias_credito)

    if tipo_documento == 'envio':
        if categoria is None:
            categoria = clasificar_categoria(getattr(archivo, 'name', '') or '')
        doc.categoria = categoria
        tarifa = TarifaCliente.activa_para(cliente, categoria) if categoria else None
        if tarifa and doc.total_libras is not None:
            doc.precio_por_libra = tarifa.precio_por_libra
            doc.monto_total = (doc.total_libras * tarifa.precio_por_libra).quantize(Decimal('0.01'))
    elif categoria is not None:
        doc.categoria = categoria

    doc.save()
    status_service.actualizar_estado_pago(doc)
    return doc
