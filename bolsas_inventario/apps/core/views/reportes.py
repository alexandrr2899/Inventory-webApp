"""
reportes.py — Reportes: stock bajo, producción día, producción rango, pigmentos.
"""
from .common import *    # noqa: F401,F403
from .stock import *     # noqa: F401,F403
from .calc import *      # noqa: F401,F403
from .payloads import *  # noqa: F401,F403


# ─── REPORTES ─────────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('ver_reportes'), raise_exception=True)
@_timed_view('reporte_stock_bajo')
def reporte_stock_bajo(request):
    items_bajo = [
        {'item': i, 'stock': i.stock_calc, 'deficit': i.stock_minimo - i.stock_calc}
        for i in (
            Item.objects
            .filter(activo=True)
            .select_related('categoria')
            .annotate(stock_calc=_STOCK_ANN)
            .filter(stock_calc__lte=F('stock_minimo'))
            .order_by('orden', 'nombre')
        )
    ]

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="stock_bajo.csv"'
        response.write('﻿')
        writer = csv.writer(response)
        writer.writerow(['Código', 'Nombre', 'Tipo', 'Categoría', 'Stock Actual', 'Stock Mínimo', 'Déficit', 'Unidad'])
        for r in items_bajo:
            writer.writerow([
                r['item'].codigo, r['item'].nombre,
                r['item'].get_tipo_display(),
                r['item'].categoria.nombre if r['item'].categoria else '',
                r['stock'], r['item'].stock_minimo, r['deficit'],
                r['item'].unidad_medida
            ])
        return response

    return render(request, 'reportes/stock_bajo.html', {'items_bajo': items_bajo})


@login_required
@permission_required(_perm('ver_reportes'), raise_exception=True)
@_timed_view('reporte_produccion')
def reporte_produccion(request):
    fecha_str = request.GET.get('fecha', '')
    if fecha_str:
        try:
            from datetime import datetime
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha = date.today()
    else:
        fecha = date.today()

    produccion = _calcular_produccion(fecha)

    # Detalles de los conteos camiseta usados para producción de día
    detalle_manana = []
    detalle_tarde  = []
    if produccion['tiene_manana']:
        conteo_m = (
            Conteo.objects
            .filter(fecha=fecha, turno='manana', tipo_conteo='camiseta', anulado=False)
            .order_by('fecha_hora_conteo')
            .first()
        )
        if conteo_m:
            detalle_manana = (
                ConteoDetalle.objects
                .filter(conteo=conteo_m, item__tipo='producto')
                .select_related('item')
            )

    if produccion['tiene_tarde']:
        conteo_t = (
            Conteo.objects
            .filter(fecha=fecha, turno='tarde', tipo_conteo='camiseta', anulado=False)
            .order_by('-fecha_hora_conteo')
            .first()
        )
        if conteo_t:
            detalle_tarde = (
                ConteoDetalle.objects
                .filter(conteo=conteo_t, item__tipo='producto')
                .select_related('item')
            )

    # Detalle del conteo mañana siguiente (para producción de noche)
    detalle_manana_sig = []
    if produccion['tiene_manana_sig']:
        from datetime import timedelta as _td
        fecha_sig = fecha + _td(days=1)
        conteo_ms = (
            Conteo.objects
            .filter(fecha=fecha_sig, turno='manana', tipo_conteo='camiseta', anulado=False)
            .order_by('fecha_hora_conteo')
            .first()
        )
        if conteo_ms:
            detalle_manana_sig = (
                ConteoDetalle.objects
                .filter(conteo=conteo_ms, item__tipo='producto')
                .select_related('item')
            )

    # Salidas del tramo día (entre conteo mañana y conteo tarde)
    if produccion['hora_manana'] and produccion['hora_tarde']:
        salidas_detalle_dia = (
            DetalleMovimiento.objects
            .filter(
                movimiento__tipo_movimiento='salida',
                movimiento__anulado=False,
                movimiento__eliminado=False,
                movimiento__fecha_movimiento__gt=produccion['hora_manana'],
                movimiento__fecha_movimiento__lt=produccion['hora_tarde'],
                item__tipo='producto',
            )
            .select_related('item', 'cliente', 'movimiento')
        )
    else:
        salidas_detalle_dia = []

    # Salidas del tramo noche (entre conteo tarde y conteo mañana siguiente)
    if produccion['hora_tarde'] and produccion['hora_manana_sig']:
        salidas_detalle_noche = (
            DetalleMovimiento.objects
            .filter(
                movimiento__tipo_movimiento='salida',
                movimiento__anulado=False,
                movimiento__eliminado=False,
                movimiento__fecha_movimiento__gt=produccion['hora_tarde'],
                movimiento__fecha_movimiento__lt=produccion['hora_manana_sig'],
                item__tipo='producto',
            )
            .select_related('item', 'cliente', 'movimiento')
        )
    else:
        salidas_detalle_noche = []

    context = {
        'fecha': fecha,
        'produccion': produccion,
        'detalle_manana': detalle_manana,
        'detalle_tarde': detalle_tarde,
        'detalle_manana_sig': detalle_manana_sig,
        'salidas_detalle_dia': salidas_detalle_dia,
        'salidas_detalle_noche': salidas_detalle_noche,
        # compat con referencias antiguas al template
        'salidas_detalle': salidas_detalle_dia,
    }
    return render(request, 'reportes/produccion.html', context)


@login_required
@permission_required(_perm('ver_reportes'), raise_exception=True)
@_timed_view('reporte_produccion_avanzado')
def reporte_produccion_avanzado(request):
    """
    Reporte de producción + salidas PT usando lógica de tramos entre
    conteos consecutivos (soporta fines de semana y rangos sin conteos).

    Un tramo = par (conteo_ini, conteo_fin) consecutivos tipo Camiseta.
    Producción = total_fin − total_ini + salidas entre conteos.
    """
    from datetime import datetime as _dt

    hoy = date.today()
    MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
             'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

    # ── Filtros ─────────────────────────────────────────────────────────────────
    def _parse_date(key, fallback):
        try:
            return _dt.strptime(request.GET.get(key, ''), '%Y-%m-%d').date()
        except ValueError:
            return fallback

    fecha_fin    = _parse_date('fecha_fin',    hoy)
    fecha_inicio = _parse_date('fecha_inicio', fecha_fin - timedelta(days=6))
    if fecha_fin < fecha_inicio:
        fecha_fin = fecha_inicio
    if (fecha_fin - fecha_inicio).days > 120:
        fecha_inicio = fecha_fin - timedelta(days=120)
        messages.warning(request, 'El reporte avanzado se limitó a 120 días para mantener tiempos de respuesta estables.')

    agrupar_por = request.GET.get('agrupar_por', 'dia')
    if agrupar_por not in ('dia', 'semana', 'mes'):
        agrupar_por = 'dia'

    export = request.GET.get('export', '')

    # ── Tramos de producción ────────────────────────────────────────────────────
    tramos = _calcular_tramos(fecha_inicio, fecha_fin)

    # ── Salidas de PT por fecha_movimiento.date() (KPI y desglose por producto) ─
    salidas_qs = (
        DetalleMovimiento.objects
        .filter(
            movimiento__tipo_movimiento='salida',
            movimiento__anulado=False,
            movimiento__eliminado=False,
            movimiento__fecha_movimiento__date__range=[fecha_inicio, fecha_fin],
            item__tipo='producto',
        )
        .select_related('movimiento', 'item')
        .only(
            'cantidad', 'item_id',
            'item__nombre', 'item__orden', 'item__unidad_medida', 'item__codigo',
            'movimiento__fecha_movimiento',
        )
    )
    sal_x_item: dict = {}       # item_pk → {'item': obj, 'total': qty}
    total_salidas_rango = Decimal('0')
    for det in salidas_qs:
        pk = det.item_id
        if pk not in sal_x_item:
            sal_x_item[pk] = {'item': det.item, 'total': Decimal('0')}
        sal_x_item[pk]['total'] += det.cantidad
        total_salidas_rango += det.cantidad

    # ── Totales globales ────────────────────────────────────────────────────────
    total_prod              = sum(t['produccion'] for t in tramos)
    total_salidas_formula   = sum(t['salidas']    for t in tramos)
    total_diferencia_formula= total_prod - total_salidas_formula   # consistente con tabla
    total_diferencia        = total_prod - total_salidas_rango     # para tarjeta resumen
    num_tramos           = len(tramos)
    num_dias_rango       = (fecha_fin - fecha_inicio).days + 1
    n_dia       = sum(1 for t in tramos if t['tipo'] == 'dia')
    n_noche     = sum(1 for t in tramos if t['tipo'] == 'noche')
    n_extendido = sum(1 for t in tramos if t['tipo'] == 'extendido')

    # ── Agrupación ──────────────────────────────────────────────────────────────
    def _gkey(tramo):
        f = tramo['fecha_asignada']
        if agrupar_por == 'dia':    return f
        if agrupar_por == 'semana': iso = f.isocalendar(); return (iso[0], iso[1])
        return (f.year, f.month)

    def _glabel(key):
        if agrupar_por == 'dia':
            return key.strftime('%d/%m/%Y')
        if agrupar_por == 'semana':
            y, w = key; return f'Sem. {w:02d} / {y}'
        y, m = key; return f'{MESES[m]} {y}'

    grupos = []
    cur_key = cur_g = None
    for t in tramos:
        k = _gkey(t)
        if k != cur_key:
            if cur_g:
                cur_g['diferencia'] = cur_g['prod_total'] - cur_g['salidas']
                grupos.append(cur_g)
            cur_key = k
            cur_g = {
                'key': k, 'label': _glabel(k),
                'prod_total':      Decimal('0'),
                'salidas':         Decimal('0'),
                'diferencia':      Decimal('0'),
                'num_tramos':      0,
                'tramos':          [],
            }
        cur_g['prod_total'] += t['produccion']
        cur_g['salidas']    += t['salidas']
        cur_g['num_tramos'] += 1
        cur_g['tramos'].append(t)
    if cur_g:
        cur_g['diferencia'] = cur_g['prod_total'] - cur_g['salidas']
        grupos.append(cur_g)

    # ── Por producto ────────────────────────────────────────────────────────────
    prod_x_item: dict = {}   # item_pk → Decimal
    for t in tramos:
        for pk, qty in t['por_item'].items():
            prod_x_item[pk] = prod_x_item.get(pk, Decimal('0')) + qty

    all_pks = set(prod_x_item.keys()) | set(sal_x_item.keys())
    items_pt = (
        Item.objects
        .filter(pk__in=all_pks, tipo='producto', activo=True)
        .order_by('orden', 'nombre')
    )
    por_producto = []
    for item in items_pt:
        prod_item = prod_x_item.get(item.pk, Decimal('0'))
        sal_item  = sal_x_item.get(item.pk, {}).get('total', Decimal('0'))
        por_producto.append({
            'item':       item,
            'prod_total': prod_item,
            'salidas':    sal_item,
            'diferencia': prod_item - sal_item,
        })

    # ── CSV export ──────────────────────────────────────────────────────────────
    if export == 'csv':
        resp = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        fname = f'produccion_{fecha_inicio}_{fecha_fin}_{agrupar_por}.csv'
        resp['Content-Disposition'] = f'attachment; filename="{fname}"'
        w = csv.writer(resp)
        w.writerow(['Período', 'Tipo', 'Tramo', 'Duración (h)', 'Producción', 'Salidas (fórmula)', 'Diferencia'])
        tipo_labels = {'dia': 'Día', 'noche': 'Noche', 'extendido': 'Extendido'}
        for g in grupos:
            for t in g['tramos']:
                w.writerow([
                    g['label'],
                    tipo_labels.get(t['tipo'], t['tipo']),
                    t['label_rango'],
                    t['duracion_h'],
                    t['produccion'],
                    t['salidas'],
                    t['produccion'] - t['salidas'],
                ])
        w.writerow([])
        w.writerow(['Producto', 'Producción', 'Salidas (rango)', 'Diferencia'])
        for p in por_producto:
            w.writerow([p['item'].nombre, p['prod_total'], p['salidas'], p['diferencia']])
        return resp

    return render(request, 'reportes/produccion_avanzado.html', {
        'fecha_inicio':           fecha_inicio,
        'fecha_fin':              fecha_fin,
        'agrupar_por':            agrupar_por,
        'grupos':                 grupos,
        'tramos':                 tramos,
        'por_producto':           por_producto,
        'total_prod':             total_prod,
        'total_salidas':              total_salidas_rango,
        'total_salidas_formula':      total_salidas_formula,
        'total_diferencia':           total_diferencia,            # prod - salidas rango (tarjeta)
        'total_diferencia_formula':   total_diferencia_formula,    # prod - salidas fórmula (tabla)
        'num_tramos':             num_tramos,
        'num_dias_rango':         num_dias_rango,
        'n_dia':                  n_dia,
        'n_noche':                n_noche,
        'n_extendido':            n_extendido,
    })


