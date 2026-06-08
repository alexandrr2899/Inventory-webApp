"""notificaciones.py — Panel de envío manual de reportes a n8n/Telegram."""
from .common import *    # noqa: F401,F403
from .payloads import *  # noqa: F401,F403


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
        payload['enviado_por'] = request.user.username
        ok = send_event(cfg['event_type'], payload)
        event_log.info('[EVENT] reporte_manual_enviado user=%s tipo=%s ok=%s', request.user.username, tipo, ok)

        if ok:
            messages.success(request, f'Reporte enviado: {cfg["titulo"]}.')
        elif not getattr(settings, 'N8N_WEBHOOK_URL', ''):
            messages.warning(request, 'N8N_WEBHOOK_URL no está configurado. El reporte se generó, pero no se envió.')
        else:
            messages.warning(request, 'No se pudo enviar el reporte al webhook. Revisá logs o n8n.')
        return redirect('notificaciones_panel')

    return render(request, 'notificaciones/panel.html', {
        'reportes': reportes,
        'webhook_configurado': bool(getattr(settings, 'N8N_WEBHOOK_URL', '')),
    })
