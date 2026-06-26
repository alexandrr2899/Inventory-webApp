"""facturas_api.py — Endpoint de ingesta automática (n8n → Google Drive).

Recibe un PDF por POST multipart, lo procesa igual que la subida manual (detecta
tipo, extrae datos, empareja cliente por nombre) y crea el documento como pendiente.
Autenticación por token compartido (header X-API-Key), sin sesión.
"""
from .common import *  # noqa: F401,F403

from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt

from ..models import DocumentoFactura
from ..services.facturas import bulk_service, invoice_service
from ..services.facturas.pdf_extractors import filename_extractor


def _token_valido(request):
    esperado = getattr(settings, 'FACTURAS_INGEST_TOKEN', '') or ''
    if not esperado:
        return None  # endpoint deshabilitado (sin token configurado)
    recibido = request.META.get('HTTP_X_API_KEY', '')
    return constant_time_compare(recibido, esperado)


@csrf_exempt
@facturas_enabled
@require_POST
def factura_api_ingest(request):
    valido = _token_valido(request)
    if valido is None:
        return JsonResponse({'ok': False, 'error': 'ingesta no configurada'}, status=503)
    if not valido:
        return JsonResponse({'ok': False, 'error': 'token inválido'}, status=401)

    archivo = request.FILES.get('archivo')
    if not archivo:
        return JsonResponse({'ok': False, 'error': 'falta el archivo (campo "archivo")'}, status=400)

    tipo = invoice_service.detectar_tipo(archivo.name)
    nombre_cli = filename_extractor.extraer_de_nombre(archivo.name).get('cliente_nombre', '')
    cliente = bulk_service.match_cliente(nombre_cli)
    if cliente is None:
        return JsonResponse({
            'ok': False, 'error': 'cliente no encontrado',
            'cliente_sugerido': nombre_cli, 'archivo': archivo.name,
        }, status=422)

    archivo.seek(0)
    prev = invoice_service.previsualizar(tipo, archivo)
    datos = prev['datos']
    numero = datos.get('numero_documento', '')

    # Deduplicación: mismo cliente + tipo + número ya existente → no duplicar.
    if numero and DocumentoFactura.objects.filter(
            cliente=cliente, tipo_documento=tipo, numero_documento=numero).exists():
        existente = DocumentoFactura.objects.filter(
            cliente=cliente, tipo_documento=tipo, numero_documento=numero).first()
        return JsonResponse({
            'ok': True, 'duplicado': True, 'id': existente.pk,
            'cliente': cliente.nombre, 'numero': numero,
        }, status=200)

    archivo.seek(0)
    doc = invoice_service.crear_documento(
        cliente=cliente, tipo_documento=tipo, archivo=archivo,
        producto=datos.get('producto'), datos=datos,
        texto_extraido=prev['texto_extraido'],
    )
    return JsonResponse({
        'ok': True, 'id': doc.pk, 'cliente': cliente.nombre,
        'tipo': doc.tipo_documento, 'numero': doc.numero_documento,
        'monto_total': str(doc.monto_total),
    }, status=201)
