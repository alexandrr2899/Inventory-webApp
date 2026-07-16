"""facturas_api.py — Endpoint de ingesta automática (n8n → Google Drive).

Recibe un PDF por POST multipart, lo procesa igual que la subida manual (detecta
tipo, extrae datos, empareja cliente por nombre) y crea el documento como pendiente.
Autenticación por token compartido (header X-API-Key), sin sesión.
"""
from .common import *  # noqa: F401,F403

from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt

from ..models import Cliente, DocumentoFactura
from ..services.facturas import bulk_service, invoice_service
from ..services.facturas.pdf_extractors import filename_extractor


def _token_valido(request):
    esperado = getattr(settings, 'FACTURAS_INGEST_TOKEN', '') or ''
    if not esperado:
        return None  # endpoint deshabilitado (sin token configurado)
    recibido = request.META.get('HTTP_X_API_KEY', '')
    return constant_time_compare(recibido, esperado)


# Rate-limit de intentos fallidos de token por IP (anti fuerza bruta del X-API-Key).
# Solo cuentan los fallos: el tráfico legítimo con token válido nunca se penaliza.
_INGEST_MAX_FALLOS = 10
_INGEST_VENTANA_SEG = 300  # 5 minutos


def _ingest_bloqueado(ip):
    return cache.get(f'ingest_fail:{ip}', 0) >= _INGEST_MAX_FALLOS


def _ingest_registrar_fallo(ip):
    key = f'ingest_fail:{ip}'
    try:
        cache.incr(key)
    except ValueError:
        # La clave no existía (o expiró): iniciar la ventana.
        cache.set(key, 1, _INGEST_VENTANA_SEG)


def _cliente_sin_identificar():
    cliente, _created = Cliente.objects.get_or_create(
        nombre='Sin identificar',
        defaults={'activo': True},
    )
    if not cliente.activo:
        cliente.activo = True
        cliente.save(update_fields=['activo'])
    return cliente


@csrf_exempt
@facturas_enabled
@require_POST
def factura_api_ingest(request):
    ip = _get_client_ip(request)
    if _ingest_bloqueado(ip):
        return JsonResponse(
            {'ok': False, 'error': 'demasiados intentos, intente más tarde'}, status=429)
    valido = _token_valido(request)
    if valido is None:
        return JsonResponse({'ok': False, 'error': 'ingesta no configurada'}, status=503)
    if not valido:
        _ingest_registrar_fallo(ip)
        return JsonResponse({'ok': False, 'error': 'token inválido'}, status=401)

    archivo = request.FILES.get('archivo')
    if not archivo:
        return JsonResponse({'ok': False, 'error': 'falta el archivo (campo "archivo")'}, status=400)

    _MAX_BYTES = 25 * 1024 * 1024
    if getattr(archivo, 'size', 0) and archivo.size > _MAX_BYTES:
        return JsonResponse({'ok': False, 'error': 'archivo demasiado grande'}, status=413)

    # Validar que sea realmente un PDF (extensión + cabecera mágica), igual que
    # la subida manual. Evita procesar archivos arbitrarios en el endpoint sin
    # sesión aunque el token sea válido.
    if os.path.splitext(archivo.name)[1].lower() != '.pdf':
        return JsonResponse({'ok': False, 'error': 'solo se aceptan archivos PDF'}, status=400)
    cabecera = archivo.read(5)
    archivo.seek(0)
    if not cabecera.startswith(b'%PDF'):
        return JsonResponse({'ok': False, 'error': 'el archivo no es un PDF válido'}, status=400)

    tipo = invoice_service.detectar_tipo(archivo.name)
    nombre_cli = filename_extractor.extraer_de_nombre(archivo.name).get('cliente_nombre', '')
    cliente = bulk_service.match_cliente(nombre_cli, solo_exacto=True)
    requiere_revision = cliente is None
    if requiere_revision:
        cliente = _cliente_sin_identificar()

    archivo.seek(0)
    try:
        prev = invoice_service.previsualizar(tipo, archivo)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'no se pudo procesar el PDF'}, status=400)
    datos = prev['datos']
    numero = datos.get('numero_documento', '')

    # Deduplicación: mismo cliente + tipo + número ya existente → no duplicar.
    if numero:
        existente = DocumentoFactura.objects.filter(
            cliente=cliente, tipo_documento=tipo, numero_documento=numero).first()
        if existente:
            return JsonResponse({
                'ok': True, 'duplicado': True, 'id': existente.pk,
                'cliente': cliente.nombre, 'numero': numero,
            }, status=200)

    archivo.seek(0)
    doc = invoice_service.crear_documento(
        cliente=cliente, tipo_documento=tipo, archivo=archivo,
        datos=datos, texto_extraido=prev['texto_extraido'],
    )
    if requiere_revision:
        doc.notas = (
            'Cliente no encontrado en ingesta automática.\n'
            f'Cliente sugerido por archivo: {nombre_cli or "(sin nombre detectado)"}\n'
            f'Archivo original: {archivo.name}'
        )
        doc.save(update_fields=['notas'])
    return JsonResponse({
        'ok': True, 'id': doc.pk, 'cliente': cliente.nombre,
        'tipo': doc.tipo_documento, 'numero': doc.numero_documento,
        'monto_total': str(doc.monto_total),
        'requiere_revision': requiere_revision,
        'cliente_sugerido': nombre_cli if requiere_revision else '',
    }, status=201)
