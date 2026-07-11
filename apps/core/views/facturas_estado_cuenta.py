"""facturas_estado_cuenta.py — Estado de cuenta por cliente (HTML y PDF)."""
import os
from io import BytesIO

from django.template.loader import render_to_string
from xhtml2pdf import pisa

from .common import *  # noqa: F401,F403

from ..models import Cliente
from ..services.facturas import estado_cuenta_service


def _parse_fecha(raw, default):
    if not raw:
        return default
    try:
        return dt_datetime.strptime(raw, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return default


def _pdf_link_callback(uri, rel):
    """Resuelve URLs /static/ y /media/ a rutas de archivo para xhtml2pdf."""
    if uri.startswith(settings.MEDIA_URL):
        return os.path.join(settings.MEDIA_ROOT, uri[len(settings.MEDIA_URL):])
    if uri.startswith(settings.STATIC_URL):
        rel_path = uri[len(settings.STATIC_URL):]
        candidato = os.path.join(settings.STATIC_ROOT, rel_path)
        if os.path.exists(candidato):
            return candidato
        for d in settings.STATICFILES_DIRS:
            alt = os.path.join(d, rel_path)
            if os.path.exists(alt):
                return alt
        return candidato
    return uri


def _render_pdf(html):
    salida = BytesIO()
    resultado = pisa.CreatePDF(src=html, dest=salida, link_callback=_pdf_link_callback, encoding='utf-8')
    if resultado.err:
        return None
    return salida.getvalue()


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def cliente_estado_cuenta(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    hoy = timezone.localdate()
    hasta = _parse_fecha(request.GET.get('hasta'), hoy)
    desde = _parse_fecha(request.GET.get('desde'), hasta - timedelta(days=60))
    datos = estado_cuenta_service.build(cliente, desde, hasta)
    es_pdf = request.GET.get('format') == 'pdf'
    html = render_to_string('facturas/estado_cuenta.html', {'es_pdf': es_pdf, **datos}, request=request)
    if not es_pdf:
        return HttpResponse(html)
    pdf = _render_pdf(html)
    if pdf is None:
        return HttpResponse('Error al generar el PDF.', status=500)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="estado-cuenta-{cliente.pk}-{hasta.isoformat()}.pdf"'
    return resp
