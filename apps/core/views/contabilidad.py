"""Panel financiero, CRUD de gastos, categorías y exportaciones."""
import csv
import logging
import mimetypes
import os
from datetime import datetime
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST
from xhtml2pdf import pisa

from .common import _perm
from ..forms import CategoriaGastoForm, GastoForm
from ..models import CategoriaGasto, Gasto, MetodoPago
from ..services import contabilidad as contabilidad_service


log = logging.getLogger(__name__)
PERMISOS_GASTOS = (_perm('ver_contabilidad'), _perm('administrar_gastos'))
PERMISOS_CATEGORIAS = (
    _perm('ver_contabilidad'), _perm('administrar_categorias_gasto'),
)


def _fecha(raw, default):
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date() if raw else default
    except (TypeError, ValueError):
        return default


def _filtros_gastos(request):
    hoy = timezone.localdate()
    desde = _fecha(request.GET.get('desde'), hoy.replace(day=1))
    hasta = _fecha(request.GET.get('hasta'), hoy)
    if desde > hasta:
        desde, hasta = hasta, desde

    qs = Gasto.objects.filter(fecha__range=(desde, hasta)).select_related(
        'categoria', 'metodo_pago', 'registrado_por',
    )
    categoria = request.GET.get('categoria', '').strip()
    metodo = request.GET.get('metodo_pago', '').strip()
    proveedor = request.GET.get('proveedor', '').strip()
    texto = request.GET.get('q', '').strip()
    if categoria.isdigit():
        qs = qs.filter(categoria_id=int(categoria))
    else:
        categoria = ''
    if metodo.isdigit():
        qs = qs.filter(metodo_pago_id=int(metodo))
    else:
        metodo = ''
    if proveedor:
        qs = qs.filter(proveedor__icontains=proveedor)
    if texto:
        qs = qs.filter(
            Q(descripcion__icontains=texto)
            | Q(proveedor__icontains=texto)
            | Q(referencia__icontains=texto)
            | Q(notas__icontains=texto)
        )
    return qs, {
        'desde': desde,
        'hasta': hasta,
        'categoria_seleccionada': categoria,
        'metodo_seleccionado': metodo,
        'proveedor': proveedor,
        'q': texto,
        'hay_filtros_gasto': bool(categoria or metodo or proveedor or texto),
    }


def _query_sin_pagina(request):
    params = request.GET.copy()
    params.pop('page', None)
    params.pop('format', None)
    return params.urlencode()


@login_required
@permission_required(_perm('ver_contabilidad'), raise_exception=True)
def contabilidad_panel(request):
    gastos, filtros = _filtros_gastos(request)
    resumen = contabilidad_service.resumen_financiero(
        filtros['desde'], filtros['hasta'],
    )
    desglose = contabilidad_service.gastos_por_categoria(gastos)
    page = Paginator(gastos, 25).get_page(request.GET.get('page'))
    return render(request, 'contabilidad/panel.html', {
        **filtros,
        'resumen': resumen,
        'desglose': desglose,
        'gastos_filtrados_total': contabilidad_service.total_gastos(gastos),
        'gastos': page,
        'page_obj': page,
        'categorias': CategoriaGasto.objects.all(),
        'metodos_pago': MetodoPago.objects.all(),
        'query_filtros': _query_sin_pagina(request),
        'pagination_query': _query_sin_pagina(request),
    })


@login_required
@permission_required(PERMISOS_GASTOS, raise_exception=True)
def gasto_crear(request):
    if request.method == 'POST':
        form = GastoForm(request.POST, request.FILES)
        if form.is_valid():
            gasto = form.save(commit=False)
            gasto.registrado_por = request.user
            gasto.save()
            messages.success(request, 'Gasto registrado correctamente.')
            return redirect('gasto_detalle', pk=gasto.pk)
    else:
        form = GastoForm(initial={'fecha': timezone.localdate()})
    return render(request, 'contabilidad/gasto_form.html', {
        'form': form, 'titulo': 'Registrar gasto',
    })


@login_required
@permission_required(_perm('ver_contabilidad'), raise_exception=True)
def gasto_detalle(request, pk):
    gasto = get_object_or_404(
        Gasto.objects.select_related('categoria', 'metodo_pago', 'registrado_por'), pk=pk,
    )
    return render(request, 'contabilidad/gasto_detalle.html', {'gasto': gasto})


@login_required
@permission_required(PERMISOS_GASTOS, raise_exception=True)
def gasto_editar(request, pk):
    gasto = get_object_or_404(Gasto, pk=pk)
    if request.method == 'POST':
        form = GastoForm(request.POST, request.FILES, instance=gasto)
        if form.is_valid():
            form.save()
            messages.success(request, 'Gasto actualizado correctamente.')
            return redirect('gasto_detalle', pk=gasto.pk)
    else:
        form = GastoForm(instance=gasto)
    return render(request, 'contabilidad/gasto_form.html', {
        'form': form, 'titulo': 'Editar gasto', 'gasto': gasto,
    })


@login_required
@permission_required(PERMISOS_GASTOS, raise_exception=True)
def gasto_eliminar(request, pk):
    gasto = get_object_or_404(Gasto, pk=pk)
    if request.method == 'POST':
        gasto.delete()
        messages.success(request, 'Gasto eliminado definitivamente.')
        return redirect('contabilidad_panel')
    return render(request, 'contabilidad/gasto_confirmar_eliminar.html', {'gasto': gasto})


@login_required
@permission_required(_perm('ver_contabilidad'), raise_exception=True)
def gasto_comprobante(request, pk):
    gasto = get_object_or_404(Gasto, pk=pk)
    if not gasto.comprobante:
        raise Http404('El gasto no tiene comprobante.')
    try:
        archivo = gasto.comprobante.open('rb')
    except (FileNotFoundError, OSError, ValueError):
        raise Http404('Archivo no encontrado.')
    nombre = os.path.basename(gasto.comprobante.name) or f'comprobante-{gasto.pk}'
    tipo = mimetypes.guess_type(nombre)[0] or 'application/octet-stream'
    return FileResponse(archivo, content_type=tipo, filename=nombre)


@login_required
@permission_required(PERMISOS_CATEGORIAS, raise_exception=True)
def categoria_gasto_lista(request):
    categorias = CategoriaGasto.objects.annotate(cantidad_gastos=Count('gastos'))
    return render(request, 'contabilidad/categorias_lista.html', {'categorias': categorias})


@login_required
@permission_required(PERMISOS_CATEGORIAS, raise_exception=True)
def categoria_gasto_crear(request):
    if request.method == 'POST':
        form = CategoriaGastoForm(request.POST)
        if form.is_valid():
            categoria = form.save()
            messages.success(request, f'Categoría "{categoria.nombre}" creada.')
            return redirect('categoria_gasto_lista')
    else:
        form = CategoriaGastoForm()
    return render(request, 'contabilidad/categoria_form.html', {
        'form': form, 'titulo': 'Nueva categoría de gasto',
    })


@login_required
@permission_required(PERMISOS_CATEGORIAS, raise_exception=True)
def categoria_gasto_editar(request, pk):
    categoria = get_object_or_404(CategoriaGasto, pk=pk)
    if request.method == 'POST':
        form = CategoriaGastoForm(request.POST, instance=categoria)
        if form.is_valid():
            form.save()
            messages.success(request, 'Categoría actualizada.')
            return redirect('categoria_gasto_lista')
    else:
        form = CategoriaGastoForm(instance=categoria)
    return render(request, 'contabilidad/categoria_form.html', {
        'form': form, 'titulo': 'Editar categoría de gasto', 'categoria': categoria,
    })


@login_required
@permission_required(PERMISOS_CATEGORIAS, raise_exception=True)
@require_POST
def categoria_gasto_toggle(request, pk):
    categoria = get_object_or_404(CategoriaGasto, pk=pk)
    categoria.activa = not categoria.activa
    categoria.save(update_fields=['activa'])
    messages.success(request, f'Categoría {"activada" if categoria.activa else "desactivada"}.')
    return redirect('categoria_gasto_lista')


@login_required
@permission_required(PERMISOS_CATEGORIAS, raise_exception=True)
@require_POST
def categoria_gasto_eliminar(request, pk):
    categoria = get_object_or_404(CategoriaGasto, pk=pk)
    try:
        categoria.delete()
    except ProtectedError:
        messages.error(request, 'No se puede eliminar una categoría que ya tiene gastos. Podés desactivarla.')
    else:
        messages.success(request, 'Categoría eliminada.')
    return redirect('categoria_gasto_lista')


def _csv_seguro(valor):
    texto = str(valor or '')
    return f"'{texto}" if texto.startswith(('=', '+', '-', '@')) else texto


@login_required
@permission_required(_perm('ver_contabilidad'), raise_exception=True)
def contabilidad_exportar_csv(request):
    gastos, filtros = _filtros_gastos(request)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="gastos-{filtros["desde"]}-{filtros["hasta"]}.csv"'
    )
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow([
        'Fecha', 'Categoría', 'Descripción', 'Monto (L)', 'Proveedor/beneficiario',
        'Método de pago', 'Referencia', 'Notas', 'Registrado por',
    ])
    for gasto in gastos:
        writer.writerow([
            gasto.fecha.isoformat(), _csv_seguro(gasto.categoria.nombre),
            _csv_seguro(gasto.descripcion), f'{gasto.monto:.2f}',
            _csv_seguro(gasto.proveedor), _csv_seguro(gasto.metodo_pago.nombre),
            _csv_seguro(gasto.referencia), _csv_seguro(gasto.notas),
            _csv_seguro(
                gasto.registrado_por.get_username() if gasto.registrado_por else ''
            ),
        ])
    return response


@login_required
@permission_required(_perm('ver_contabilidad'), raise_exception=True)
def contabilidad_exportar_pdf(request):
    gastos, filtros = _filtros_gastos(request)
    cantidad = gastos.count()
    limite = settings.CONTABILIDAD_PDF_MAX_REGISTROS
    if cantidad > limite:
        return HttpResponse(
            f'El reporte contiene {cantidad} gastos. Reducí el rango o aplicá '
            f'filtros para no superar {limite} registros.',
            status=400,
        )
    resumen = contabilidad_service.resumen_financiero(
        filtros['desde'], filtros['hasta'],
    )
    html = render_to_string('contabilidad/reporte_pdf.html', {
        **filtros,
        'resumen': resumen,
        'desglose': contabilidad_service.gastos_por_categoria(gastos),
        'gastos_filtrados_total': contabilidad_service.total_gastos(gastos),
        'cantidad_gastos': cantidad,
        'gastos': gastos,
        'generado_en': timezone.localtime(),
    })
    salida = BytesIO()
    try:
        resultado = pisa.CreatePDF(html, dest=salida, encoding='utf-8')
    except Exception:
        log.exception('Error inesperado al generar reporte PDF de Contabilidad')
        return HttpResponse('Error al generar el PDF.', status=500)
    if resultado.err:
        log.error(
            'xhtml2pdf no pudo generar reporte de Contabilidad: errores=%s',
            resultado.err,
        )
        return HttpResponse('Error al generar el PDF.', status=500)
    response = HttpResponse(salida.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="contabilidad-{filtros["desde"]}-{filtros["hasta"]}.pdf"'
    )
    return response
