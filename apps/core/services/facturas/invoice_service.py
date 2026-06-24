"""invoice_service — alta de documentos (Factura/Envío) desde PDF o datos."""
from decimal import Decimal

from django.db import transaction

from apps.core.models import DocumentoFactura, TarifaCliente
from . import pdf_service, status_service
from .pdf_extractors import filename_extractor


# Campos que un extractor puede aportar y que se copian directo al documento.
_CAMPOS_DIRECTOS = (
    'numero_documento', 'fecha_documento', 'subtotal', 'isv',
    'monto_total', 'total_libras', 'producto',
)


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

    datos.pop('_enteros', None)
    return {'texto_extraido': texto, 'datos': datos}


@transaction.atomic
def crear_documento(*, cliente, tipo_documento, archivo=None, producto=None,
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
    if producto:
        doc.producto = producto

    for campo in _CAMPOS_DIRECTOS:
        if campo in datos and datos[campo] is not None:
            setattr(doc, campo, datos[campo])

    if tipo_documento == 'envio':
        prod = producto or doc.producto
        tarifa = TarifaCliente.activa_para(cliente, prod) if prod else None
        if tarifa and doc.total_libras is not None:
            doc.precio_por_libra = tarifa.precio_por_libra
            doc.monto_total = (doc.total_libras * tarifa.precio_por_libra).quantize(Decimal('0.01'))

    doc.save()
    status_service.actualizar_estado_pago(doc)
    return doc
