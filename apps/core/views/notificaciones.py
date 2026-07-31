"""notificaciones.py — Panel de envío manual de reportes a n8n/Telegram."""
from .common import *    # noqa: F401,F403
from .payloads import *  # noqa: F401,F403

from ..models import WebPushPreference, WebPushSubscription
from ..services.web_push import user_is_push_eligible, web_push_configured

_PREFERENCE_FIELDS = ('inventario', 'operaciones', 'facturas', 'backups', 'seguridad')


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _push_access_or_403(request):
    if not user_is_push_eligible(request.user):
        raise PermissionDenied


# ─── NOTIFICACIONES MANUALES ─────────────────────────────────────────────────

@login_required
@_timed_view('notificaciones_panel')
def notificaciones_panel(request):
    if not _puede_enviar_notificaciones(request.user):
        raise PermissionDenied

    reportes = [
        {'key': key, **{k: v for k, v in cfg.items() if k not in ('builder', 'event_type')}}
        for key, cfg in _REPORTES_MANUALES.items()
    ]

    if request.method == 'POST':
        tipo = request.POST.get('tipo', '').strip()
        cfg = _REPORTES_MANUALES.get(tipo)
        if not cfg:
            messages.error(request, 'Reporte no válido.')
            return redirect('notificaciones_panel')

        payload = cfg['builder']()
        payload['enviado_por'] = request.user.get_full_name() or request.user.username
        ok = send_event(cfg['event_type'], payload)
        event_log.info('[EVENT] reporte_manual_enviado user=%s tipo=%s ok=%s', request.user.username, tipo, ok)

        if ok:
            messages.success(request, f'Reporte enviado: {cfg["titulo"]}.')
        elif not getattr(settings, 'N8N_WEBHOOK_URL', ''):
            messages.warning(request, 'N8N_WEBHOOK_URL no está configurado. El reporte se generó, pero no se envió.')
        else:
            messages.warning(request, 'No se pudo enviar el reporte al webhook. Revisá logs o n8n.')
        return redirect('notificaciones_panel')

    push_preference, _ = WebPushPreference.objects.get_or_create(user=request.user)
    return render(request, 'notificaciones/panel.html', {
        'reportes': reportes,
        'webhook_configurado': bool(getattr(settings, 'N8N_WEBHOOK_URL', '')),
        'web_push_configurado': web_push_configured(),
        'vapid_public_key': getattr(settings, 'VAPID_PUBLIC_KEY', ''),
        'push_preference': push_preference,
        'push_categories': [
            ('inventario', 'Inventario'),
            ('operaciones', 'Operaciones y reportes'),
            ('facturas', 'Facturas y cobros'),
            ('backups', 'Backups'),
            ('seguridad', 'Seguridad'),
        ],
    })


@login_required
def web_push_config(request):
    _push_access_or_403(request)
    preference, _ = WebPushPreference.objects.get_or_create(user=request.user)
    return JsonResponse({
        'configured': web_push_configured(),
        'public_key': getattr(settings, 'VAPID_PUBLIC_KEY', ''),
        'preferences': {
            field: getattr(preference, field) for field in _PREFERENCE_FIELDS
        },
    })


@login_required
@require_POST
def web_push_subscribe(request):
    _push_access_or_403(request)
    if not web_push_configured():
        return JsonResponse({'ok': False, 'error': 'Web Push no está configurado.'}, status=503)
    data = _json_body(request)
    if data is None:
        return JsonResponse({'ok': False, 'error': 'JSON inválido.'}, status=400)
    endpoint = str(data.get('endpoint', '')).strip()
    keys = data.get('keys') if isinstance(data.get('keys'), dict) else {}
    p256dh = str(keys.get('p256dh', '')).strip()
    auth = str(keys.get('auth', '')).strip()
    if not endpoint or not p256dh or not auth:
        return JsonResponse({'ok': False, 'error': 'Suscripción incompleta.'}, status=400)
    if len(endpoint) > 4096 or len(p256dh) > 1024 or len(auth) > 512:
        return JsonResponse({'ok': False, 'error': 'Suscripción demasiado larga.'}, status=400)
    subscription, created = WebPushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'user': request.user,
            'p256dh': p256dh,
            'auth': auth,
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:300],
            'last_error': '',
        },
    )
    WebPushPreference.objects.get_or_create(user=request.user)
    return JsonResponse({'ok': True, 'created': created, 'id': subscription.pk})


@login_required
@require_POST
def web_push_unsubscribe(request):
    data = _json_body(request)
    if data is None:
        return JsonResponse({'ok': False, 'error': 'JSON inválido.'}, status=400)
    endpoint = str(data.get('endpoint', '')).strip()
    if endpoint:
        WebPushSubscription.objects.filter(
            user=request.user, endpoint=endpoint).delete()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def web_push_preferences(request):
    _push_access_or_403(request)
    data = _json_body(request)
    if data is None:
        return JsonResponse({'ok': False, 'error': 'JSON inválido.'}, status=400)
    preference, _ = WebPushPreference.objects.get_or_create(user=request.user)
    for field in _PREFERENCE_FIELDS:
        if field in data:
            if not isinstance(data[field], bool):
                return JsonResponse({
                    'ok': False, 'error': f'Valor inválido para {field}.',
                }, status=400)
            setattr(preference, field, data[field])
    preference.save()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def web_push_test(request):
    _push_access_or_403(request)
    data = _json_body(request)
    if data is None:
        return JsonResponse({'ok': False, 'error': 'JSON inválido.'}, status=400)
    endpoint = str(data.get('endpoint', '')).strip()
    subscription = WebPushSubscription.objects.filter(
        user=request.user, endpoint=endpoint).first()
    if not subscription:
        return JsonResponse({'ok': False, 'error': 'Este dispositivo no está suscrito.'}, status=404)
    try:
        from ..tasks import deliver_web_push
        deliver_web_push.delay(subscription.pk, {
            'event_type': 'web_push_test',
            'category': 'operaciones',
            'title': 'Notificaciones activadas',
            'body': 'Este dispositivo puede recibir avisos de Transformadora.',
            'url': reverse('notificaciones_panel'),
            'tag': 'web-push-test',
            'icon': '/static/icons/icon-192.png',
            'badge': '/static/icons/icon-192.png',
        })
    except Exception:
        return JsonResponse({'ok': False, 'error': 'No se pudo encolar la prueba.'}, status=503)
    return JsonResponse({'ok': True})
