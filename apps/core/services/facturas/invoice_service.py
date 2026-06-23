"""invoice_service — alta de documentos (Factura/Envío) desde PDF o datos."""
from decimal import Decimal

from django.db import transaction

from apps.core.models import DocumentoFactura, TarifaCliente
from . import pdf_service, status_service


# Campos que un extractor puede aportar y que se copian directo al documento.
_CAMPOS_DIRECTOS = (
    'numero_documento', 'fecha_documento', 'subtotal', 'isv',
    'monto_total', 'total_libras', 'producto',
)


def previsualizar(tipo_documento, archivo):
    """Extrae texto y datos del PDF sin guardar nada."""
    texto = pdf_service.extraer_texto(archivo)
    datos = pdf_service.get_extractor(tipo_documento).extraer(texto)
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
