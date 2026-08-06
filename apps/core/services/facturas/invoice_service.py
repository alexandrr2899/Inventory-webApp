"""invoice_service — alta de documentos (Factura/Envío) desde PDF o datos."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.models import DocumentoFactura, TarifaCliente, CategoriaProducto
from . import payment_service, pdf_service, status_service
from .clientes import NOMBRE_SIN_IDENTIFICAR
from .pdf_extractors import filename_extractor


# Campos que un extractor puede aportar y que se copian directo al documento.
_CAMPOS_DIRECTOS = (
    'numero_documento', 'fecha_documento', 'fecha_vencimiento', 'subtotal', 'isv',
    'monto_total', 'total_libras',
)


def calcular_vencimiento(cliente, fecha_documento):
    """Fecha de vencimiento = fecha del documento + días de crédito del cliente.

    Contado (0 días) vence el MISMO día del documento: así sale 'pendiente' ese día
    y 'vencida' al siguiente, en vez de quedarse pendiente para siempre por no tener
    fecha de vencimiento.

    Devuelve None para «Sin identificar»: un documento que la ingesta no pudo
    emparejar no debe nacer vencido, y dejarle el vencimiento vacío es lo que permite
    calcularlo con los días del cliente real al identificarlo.
    """
    if not fecha_documento or cliente is None:
        return None
    if cliente.nombre == NOMBRE_SIN_IDENTIFICAR:
        return None
    return fecha_documento + timedelta(days=cliente.dias_credito or 0)


@transaction.atomic
def registrar_saldo_inicial(cliente, *, monto, fecha, notas=''):
    """Crea el documento de apertura con la deuda que el cliente ya traía.

    Se modela como documento (y no como un campo del cliente) para que reciba abonos,
    sume en lo adeudado, salga en el estado de cuenta y envejezca igual que una factura.
    Al ser el documento más viejo, el auto-reparto por antigüedad lo cobra primero.

    Vence el mismo día del corte aunque el cliente tenga días de crédito: es deuda que
    ya venía corriendo, no una venta nueva.
    """
    if saldo_inicial_de(cliente) is not None:
        raise ValidationError('Este cliente ya tiene un saldo inicial registrado.')
    doc = DocumentoFactura.objects.create(
        cliente=cliente, tipo_documento='apertura',
        numero_documento='SALDO INICIAL',
        fecha_documento=fecha, fecha_vencimiento=fecha,
        monto_total=monto, estado_revision='revisada', notas=notas,
    )
    # Si el cliente tenía crédito sin aplicar, se descuenta de la deuda vieja.
    payment_service.aplicar_saldo_a_favor(doc)
    status_service.actualizar_estado_pago(doc)
    return doc


def saldo_inicial_de(cliente):
    """El documento de apertura vigente del cliente, o None."""
    return (DocumentoFactura.objects
            .filter(cliente=cliente, tipo_documento='apertura')
            .exclude(estado_pago='anulada')
            .first())


def clasificar_categoria(haystack, con_predeterminada=True):
    """Primera categoría activa cuya palabra_clave aparece en haystack (case-insensitive).

    palabra_clave puede contener varias palabras separadas por coma: cualquiera que coincida cuenta.
    Si ninguna categoría coincide: devuelve predeterminada() si con_predeterminada=True, else None.
    """
    texto = (haystack or '').lower()
    for cat in CategoriaProducto.objects.filter(activa=True).order_by('orden', 'nombre'):
        kw = (cat.palabra_clave or '').strip()
        if kw and any(p in texto for p in (x.strip().lower() for x in kw.split(',')) if p):
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
    texto_extraido = texto_extraido or ''

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

    # Vencimiento automático (solo si no vino un vencimiento explícito en los datos).
    if not doc.fecha_vencimiento:
        doc.fecha_vencimiento = calcular_vencimiento(cliente, doc.fecha_documento)

    if tipo_documento == 'envio':
        if categoria is None:
            nombre = getattr(archivo, 'name', '') or ''
            categoria = clasificar_categoria(nombre + '\n' + texto_extraido)
        doc.categoria = categoria
        tarifa = TarifaCliente.activa_para(cliente, categoria) if categoria else None
        if tarifa and doc.total_libras is not None:
            doc.precio_por_libra = tarifa.precio_por_libra
            doc.monto_total = (doc.total_libras * tarifa.precio_por_libra).quantize(Decimal('0.01'))
    else:
        if categoria is None:
            nombre = getattr(archivo, 'name', '') or ''
            categoria = clasificar_categoria(nombre + '\n' + texto_extraido, con_predeterminada=False)
        if categoria is not None:
            doc.categoria = categoria

    doc.save()
    status_service.actualizar_estado_pago(doc)
    return doc
