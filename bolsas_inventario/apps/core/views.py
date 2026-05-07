import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.db.models import Sum, Q, Count, F, Value, DecimalField
from django.db.models.functions import Coalesce
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.core.paginator import Paginator
from datetime import date, timedelta
from decimal import Decimal
import csv
import io
import json

security_log = logging.getLogger('security')

# Shared annotation for total stock per item
_STOCK_ANN = Coalesce(
    Sum('stock__cantidad_actual'),
    Value(Decimal('0')),
    output_field=DecimalField(max_digits=12, decimal_places=2),
)

from .models import (
    Item, Categoria, Ubicacion, Stock, Maquina, Cliente,
    MovimientoInventario, DetalleMovimiento, Conteo, ConteoDetalle
)
from django.contrib.auth.models import User, Group
from .forms import (
    ItemForm, CategoriaForm, UbicacionForm, MaquinaForm, ClienteForm,
    MovimientoEntradaForm, MovimientoSalidaForm, MovimientoTransferenciaForm,
    ConteoForm, FiltroMovimientosForm, ProduccionForm, ImportarItemsForm,
    UsuarioCrearForm, UsuarioEditarForm,
)
from .services.notifications import notify_stock, send_event, send_security_event


def _perm(codename):
    """Shorthand permission string for core app."""
    return f'core.{codename}'


def _get_client_ip(request):
    """Return real client IP, respecting X-Forwarded-For from Cloudflare Tunnel."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


# ─── HELPERS DE STOCK PARA MOVIMIENTOS ────────────────────────────────────────

def _revertir_efecto_detalle(det):
    """
    Deshace el efecto de stock de un DetalleMovimiento.
    Debe llamarse dentro de transaction.atomic().
    """
    tipo = det.movimiento.tipo_movimiento

    if tipo == 'entrada':
        if det.ubicacion_destino:
            s = Stock.objects.filter(
                item=det.item, ubicacion=det.ubicacion_destino
            ).first()
            if s:
                s.cantidad_actual -= det.cantidad
                s.save()

    elif tipo == 'salida':
        if det.ubicacion_origen:
            s, _ = Stock.objects.get_or_create(
                item=det.item, ubicacion=det.ubicacion_origen,
                defaults={'cantidad_actual': Decimal('0')},
            )
            s.cantidad_actual += det.cantidad
            s.save()

    elif tipo == 'ajuste':
        if det.ubicacion_destino:
            s = Stock.objects.filter(
                item=det.item, ubicacion=det.ubicacion_destino
            ).first()
            if s:
                s.cantidad_actual -= det.cantidad
                s.save()

    elif tipo == 'transferencia':
        if det.ubicacion_origen:
            s, _ = Stock.objects.get_or_create(
                item=det.item, ubicacion=det.ubicacion_origen,
                defaults={'cantidad_actual': Decimal('0')},
            )
            s.cantidad_actual += det.cantidad
            s.save()
        if det.ubicacion_destino:
            s = Stock.objects.filter(
                item=det.item, ubicacion=det.ubicacion_destino
            ).first()
            if s:
                s.cantidad_actual -= det.cantidad
                s.save()


def _aplicar_efecto_detalle(det):
    """
    Aplica el efecto de stock de un DetalleMovimiento recién creado/editado.
    Debe llamarse dentro de transaction.atomic().
    """
    tipo = det.movimiento.tipo_movimiento

    if tipo == 'entrada':
        if det.ubicacion_destino:
            s, _ = Stock.objects.get_or_create(
                item=det.item, ubicacion=det.ubicacion_destino,
                defaults={'cantidad_actual': Decimal('0')},
            )
            s.cantidad_actual += det.cantidad
            s.save()

    elif tipo == 'salida':
        if det.ubicacion_origen:
            s = Stock.objects.filter(
                item=det.item, ubicacion=det.ubicacion_origen
            ).first()
            if s:
                s.cantidad_actual -= det.cantidad
                s.save()

    elif tipo == 'ajuste':
        if det.ubicacion_destino:
            s, _ = Stock.objects.get_or_create(
                item=det.item, ubicacion=det.ubicacion_destino,
                defaults={'cantidad_actual': Decimal('0')},
            )
            s.cantidad_actual += det.cantidad
            s.save()

    elif tipo == 'transferencia':
        if det.ubicacion_origen:
            s = Stock.objects.filter(
                item=det.item, ubicacion=det.ubicacion_origen
            ).first()
            if s:
                s.cantidad_actual -= det.cantidad
                s.save()
        if det.ubicacion_destino:
            s, _ = Stock.objects.get_or_create(
                item=det.item, ubicacion=det.ubicacion_destino,
                defaults={'cantidad_actual': Decimal('0')},
            )
            s.cantidad_actual += det.cantidad
            s.save()


def _revertir_todos_los_detalles(mov):
    """Revierte el stock de TODOS los detalles de un movimiento cabecera."""
    for det in mov.detalles.select_related(
        'item', 'ubicacion_origen', 'ubicacion_destino'
    ).all():
        _revertir_efecto_detalle(det)


def _stock_en_momento(item, ubicacion, fecha_hora):
    """
    Stock teórico de un ítem/ubicación en un momento dado, usando
    fecha_movimiento como timestamp oficial de cada movimiento.

    Algoritmo:
      1. Parte del stock actual (incluye TODOS los movimientos aplicados).
      2. Resta el efecto neto de los movimientos con fecha_movimiento > fecha_hora
         (ocurrieron después del momento de interés → deben excluirse).

    Esto es correcto independientemente de cuándo se registró cada movimiento
    en el sistema: lo que importa es su fecha_movimiento.
    """
    stock_obj = Stock.objects.filter(item=item, ubicacion=ubicacion).first()
    stock_actual = stock_obj.cantidad_actual if stock_obj else Decimal('0')

    # Movimientos cuya fecha_movimiento es POSTERIOR al momento del conteo.
    # Estos ya están aplicados al stock actual pero no debían estarlo al conteo.
    post_movs = (
        DetalleMovimiento.objects
        .filter(
            item=item,
            movimiento__anulado=False,
            movimiento__eliminado=False,
            movimiento__fecha_movimiento__gt=fecha_hora,
        )
        .filter(Q(ubicacion_destino=ubicacion) | Q(ubicacion_origen=ubicacion))
        .only('cantidad', 'ubicacion_origen_id', 'ubicacion_destino_id')
    )

    # Efecto neto de esos movimientos post-conteo sobre esta ubicación
    net_post = Decimal('0')
    for pm in post_movs:
        if pm.ubicacion_destino_id == ubicacion.pk:
            net_post += pm.cantidad   # entró a esta ubicación
        if pm.ubicacion_origen_id == ubicacion.pk:
            net_post -= pm.cantidad   # salió de esta ubicación

    # Stock al momento del conteo = stock actual − efecto de post-conteo
    return stock_actual - net_post


def _movimiento_editable(mov):
    """Retorna True si el movimiento puede ser editado/anulado."""
    return not mov.anulado and not mov.eliminado


def _cerrar_pendientes_conciliacion(item, ubicacion):
    """
    Después de aplicar un ajuste, revisa si el stock del ítem en la ubicación
    es ahora ≥ 0 y, de ser así, cierra (marca como conciliadas) todas las líneas
    de DetalleMovimiento que estén pendientes para ese ítem/ubicación.

    Debe llamarse dentro de transaction.atomic().
    """
    stock_obj = Stock.objects.filter(item=item, ubicacion=ubicacion).first()
    if not stock_obj or stock_obj.cantidad_actual < Decimal('0'):
        return 0

    ahora = timezone.now()
    pendientes = DetalleMovimiento.objects.filter(
        item=item,
        ubicacion_origen=ubicacion,
        pendiente_conciliacion=True,
        movimiento__anulado=False,
        movimiento__eliminado=False,
    )
    n = pendientes.update(pendiente_conciliacion=False, fecha_conciliacion=ahora)
    return n


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    hoy = date.today()

    # Single query: annotate stock total, filter bajo_stock in DB (no N+1)
    items_bajo_stock = list(
        Item.objects
        .filter(activo=True)
        .annotate(stock_calc=_STOCK_ANN)
        .filter(stock_calc__lte=F('stock_minimo'))
        .select_related('categoria')
        .order_by('orden', 'nombre')[:20]
    )

    ultimos_detalles = (
        DetalleMovimiento.objects
        .filter(movimiento__eliminado=False)
        .select_related('item', 'movimiento', 'movimiento__usuario')
        .order_by('-movimiento__fecha')[:10]
    )

    produccion_hoy = _calcular_produccion(hoy)

    hace_30 = timezone.now() - timedelta(days=30)
    repuestos_top = (
        DetalleMovimiento.objects
        .filter(
            movimiento__tipo_movimiento='salida',
            movimiento__anulado=False,
            movimiento__eliminado=False,
            movimiento__fecha_movimiento__gte=hace_30,
            item__tipo='repuesto',
        )
        .values('item__nombre', 'item__unidad_medida')
        .annotate(total=Sum('cantidad'))
        .order_by('-total')[:5]
    )

    total_bajo_stock = (
        Item.objects
        .filter(activo=True)
        .annotate(stock_calc=_STOCK_ANN)
        .filter(stock_calc__lte=F('stock_minimo'))
        .count()
    )

    total_pendientes_conciliacion = (
        DetalleMovimiento.objects
        .filter(
            pendiente_conciliacion=True,
            movimiento__anulado=False,
            movimiento__eliminado=False,
        )
        .count()
    )

    context = {
        'items_bajo_stock': items_bajo_stock,
        'ultimos_detalles': ultimos_detalles,
        'produccion_hoy': produccion_hoy,
        'repuestos_top': repuestos_top,
        'hoy': hoy,
        'total_items': Item.objects.filter(activo=True).count(),
        'total_bajo_stock': total_bajo_stock,
        'total_pendientes_conciliacion': total_pendientes_conciliacion,
    }
    return render(request, 'dashboard.html', context)


def _calcular_produccion(fecha):
    """
    Calcula producción de día y noche usando SOLO conteos tipo Camiseta.

    Producción de día:   conteo mañana → conteo tarde  (mismo día)
    Producción de noche: conteo tarde  → conteo mañana del día siguiente

    Fórmulas:
      prod_dia   = total_tarde     - total_manana     + salidas entre ambos conteos
      prod_noche = total_manana_sig - total_tarde     + salidas entre ambos conteos

    Reglas:
    - Solo usa conteos con tipo_conteo='camiseta'.
    - Usa .first()/.last() ordenados por fecha_hora_conteo (nunca .get()).
    - Salidas: solo movimientos activos (no anulados, no eliminados) dentro
      del rango horario exacto entre los dos conteos involucrados.
    - Si falta algún conteo no lanza error — informa qué falta.
    """
    from datetime import timedelta as _td

    qs_camiseta = Conteo.objects.filter(tipo_conteo='camiseta', anulado=False)

    # Conteo mañana: el más temprano del día (fecha_hora_conteo asc)
    conteo_manana = (
        qs_camiseta.filter(fecha=fecha, turno='manana')
        .order_by('fecha_hora_conteo')
        .first()
    )
    # Conteo tarde: el más reciente del día (fecha_hora_conteo desc)
    conteo_tarde = (
        qs_camiseta.filter(fecha=fecha, turno='tarde')
        .order_by('-fecha_hora_conteo')
        .first()
    )
    # Conteo mañana del día siguiente: el más temprano
    conteo_manana_sig = (
        qs_camiseta.filter(fecha=fecha + _td(days=1), turno='manana')
        .order_by('fecha_hora_conteo')
        .first()
    )

    def _total(conteo):
        """Suma cantidad_contada de ítems tipo 'producto' en un conteo."""
        if conteo is None:
            return None
        t = (
            ConteoDetalle.objects
            .filter(conteo=conteo, item__tipo='producto')
            .aggregate(t=Sum('cantidad_contada'))['t']
        )
        return t if t is not None else Decimal('0')

    def _salidas_entre(t_inicio, t_fin):
        """
        Suma de DetalleMovimiento de salidas activas cuya fecha_movimiento
        cae estrictamente entre t_inicio y t_fin.
        Solo ítems tipo 'producto'.
        """
        return (
            DetalleMovimiento.objects
            .filter(
                movimiento__tipo_movimiento='salida',
                movimiento__anulado=False,
                movimiento__eliminado=False,
                movimiento__fecha_movimiento__gt=t_inicio,
                movimiento__fecha_movimiento__lt=t_fin,
                item__tipo='producto',
            )
            .aggregate(t=Sum('cantidad'))['t'] or Decimal('0')
        )

    total_manana    = _total(conteo_manana)
    total_tarde     = _total(conteo_tarde)
    total_manana_sig = _total(conteo_manana_sig)

    # ── Producción de día ────────────────────────────────────────────────────
    if conteo_manana and conteo_tarde:
        salidas_dia   = _salidas_entre(
            conteo_manana.fecha_hora_conteo,
            conteo_tarde.fecha_hora_conteo,
        )
        produccion_dia  = total_tarde - total_manana + salidas_dia
        falta_dia       = None
    else:
        salidas_dia    = Decimal('0')
        produccion_dia = None
        if not conteo_manana and not conteo_tarde:
            falta_dia = 'conteo de mañana y tarde'
        elif not conteo_manana:
            falta_dia = 'conteo de mañana'
        else:
            falta_dia = 'conteo de tarde'

    # ── Producción de noche ──────────────────────────────────────────────────
    if conteo_tarde and conteo_manana_sig:
        salidas_noche   = _salidas_entre(
            conteo_tarde.fecha_hora_conteo,
            conteo_manana_sig.fecha_hora_conteo,
        )
        produccion_noche = total_manana_sig - total_tarde + salidas_noche
        falta_noche      = None
    else:
        salidas_noche    = Decimal('0')
        produccion_noche = None
        if not conteo_tarde and not conteo_manana_sig:
            falta_noche = 'conteo de tarde y mañana del día siguiente'
        elif not conteo_tarde:
            falta_noche = 'conteo de tarde'
        else:
            falta_noche = 'conteo de mañana del día siguiente'

    # ── Total estimado ───────────────────────────────────────────────────────
    if produccion_dia is not None and produccion_noche is not None:
        produccion_total = produccion_dia + produccion_noche
    elif produccion_dia is not None:
        produccion_total = produccion_dia
    else:
        produccion_total = produccion_noche  # None si tampoco hay noche

    return {
        # Producción calculada
        'produccion_dia':    produccion_dia,
        'produccion_noche':  produccion_noche,
        'produccion_total':  produccion_total,
        # Totales brutos de cada conteo
        'total_manana':      total_manana,
        'total_tarde':       total_tarde,
        'total_manana_sig':  total_manana_sig,
        # Salidas por tramo
        'salidas_dia':       salidas_dia,
        'salidas_noche':     salidas_noche,
        # Existencia de conteos
        'tiene_manana':      conteo_manana is not None,
        'tiene_tarde':       conteo_tarde is not None,
        'tiene_manana_sig':  conteo_manana_sig is not None,
        # Horarios usados (para mostrar rango)
        'hora_manana':       conteo_manana.fecha_hora_conteo     if conteo_manana     else None,
        'hora_tarde':        conteo_tarde.fecha_hora_conteo      if conteo_tarde      else None,
        'hora_manana_sig':   conteo_manana_sig.fecha_hora_conteo if conteo_manana_sig else None,
        # Qué falta (string descriptivo)
        'falta_dia':         falta_dia,
        'falta_noche':       falta_noche,
        # ── Compatibilidad con reporte_produccion template ────────────────────
        'produccion':        produccion_dia,
        'conteo_manana':     total_manana,
        'conteo_tarde':      total_tarde,
        'salidas':           salidas_dia,
    }


def _calcular_produccion_rango(fecha_inicio, fecha_fin):
    """
    Calcula producción día/noche para cada fecha del rango [fecha_inicio, fecha_fin]
    usando una sola ronda de consultas DB (batch).

    Devuelve:
        {
            date: {
                'prod_dia':   Decimal,
                'prod_noche': Decimal,
                'tiene_dia':  bool,
                'tiene_noche': bool,
                'por_item':   {item_pk: {'dia': Decimal, 'noche': Decimal}},
            },
            ...
        }
    Misma lógica que _calcular_produccion(fecha) pero vectorizada.
    """
    # Extender un día para capturar el conteo mañana del día siguiente
    fecha_fin_ext = fecha_fin + timedelta(days=1)

    # ── 1. Conteos ──────────────────────────────────────────────────────────────
    conteos = list(
        Conteo.objects
        .filter(tipo_conteo='camiseta', anulado=False,
                fecha__range=[fecha_inicio, fecha_fin_ext])
        .order_by('fecha', 'turno', 'fecha_hora_conteo')
    )

    # Índices: fecha → mejor conteo (mañana=earliest, tarde=latest)
    conteos_manana: dict = {}
    conteos_tarde: dict  = {}
    for c in conteos:
        if c.turno == 'manana':
            if c.fecha not in conteos_manana or c.fecha_hora_conteo < conteos_manana[c.fecha].fecha_hora_conteo:
                conteos_manana[c.fecha] = c
        elif c.turno == 'tarde':
            if c.fecha not in conteos_tarde or c.fecha_hora_conteo > conteos_tarde[c.fecha].fecha_hora_conteo:
                conteos_tarde[c.fecha] = c

    # ── 2. ConteoDetalle batch ──────────────────────────────────────────────────
    conteo_ids = [c.pk for c in conteos]
    detalles_x_conteo: dict = {}   # conteo_pk → {item_pk: cantidad}
    if conteo_ids:
        for cd in (
            ConteoDetalle.objects
            .filter(conteo_id__in=conteo_ids, item__tipo='producto')
            .select_related('item')
        ):
            detalles_x_conteo.setdefault(cd.conteo_id, {})[cd.item_id] = cd.cantidad_contada

    # ── 3. Salidas batch (para la fórmula de producción) ───────────────────────
    all_times = [c.fecha_hora_conteo for c in conteos]
    salidas_prod: list = []   # [(fecha_movimiento, item_pk, cantidad)]
    if all_times:
        t_min, t_max = min(all_times), max(all_times)
        for det in (
            DetalleMovimiento.objects
            .filter(
                movimiento__tipo_movimiento='salida',
                movimiento__anulado=False,
                movimiento__eliminado=False,
                movimiento__fecha_movimiento__gte=t_min,
                movimiento__fecha_movimiento__lte=t_max,
                item__tipo='producto',
            )
            .select_related('movimiento')
            .only('item_id', 'cantidad', 'movimiento__fecha_movimiento')
        ):
            salidas_prod.append(
                (det.movimiento.fecha_movimiento, det.item_id, det.cantidad)
            )

    # ── Funciones auxiliares ────────────────────────────────────────────────────
    def _items(conteo_pk):
        return detalles_x_conteo.get(conteo_pk, {})

    def _salidas_items_entre(t0, t1):
        """Dict {item_pk: qty} para salidas con t0 < fecha_movimiento < t1."""
        r: dict = {}
        for t, pk, qty in salidas_prod:
            if t0 < t < t1:
                r[pk] = r.get(pk, Decimal('0')) + qty
        return r

    # ── 4. Calcular por día ─────────────────────────────────────────────────────
    result: dict = {}
    cur = fecha_inicio
    while cur <= fecha_fin:
        cm  = conteos_manana.get(cur)
        ct  = conteos_tarde.get(cur)
        cms = conteos_manana.get(cur + timedelta(days=1))

        prod_dia   = Decimal('0')
        prod_noche = Decimal('0')
        tiene_dia  = tiene_noche = False
        por_item: dict = {}

        # Producción día
        if cm and ct:
            items_m = _items(cm.pk)
            items_t = _items(ct.pk)
            sal_dia = _salidas_items_entre(cm.fecha_hora_conteo, ct.fecha_hora_conteo)

            prod_dia = (
                sum(items_t.values(), Decimal('0'))
                - sum(items_m.values(), Decimal('0'))
                + sum(sal_dia.values(), Decimal('0'))
            )
            tiene_dia = True

            for pk in set(items_m) | set(items_t):
                por_item.setdefault(pk, {'dia': Decimal('0'), 'noche': Decimal('0')})
                por_item[pk]['dia'] = (
                    items_t.get(pk, Decimal('0'))
                    - items_m.get(pk, Decimal('0'))
                    + sal_dia.get(pk, Decimal('0'))
                )

        # Producción noche
        if ct and cms:
            items_t  = _items(ct.pk)
            items_ms = _items(cms.pk)
            sal_noch = _salidas_items_entre(ct.fecha_hora_conteo, cms.fecha_hora_conteo)

            prod_noche = (
                sum(items_ms.values(), Decimal('0'))
                - sum(items_t.values(), Decimal('0'))
                + sum(sal_noch.values(), Decimal('0'))
            )
            tiene_noche = True

            for pk in set(items_t) | set(items_ms):
                por_item.setdefault(pk, {'dia': Decimal('0'), 'noche': Decimal('0')})
                por_item[pk]['noche'] = (
                    items_ms.get(pk, Decimal('0'))
                    - items_t.get(pk, Decimal('0'))
                    + sal_noch.get(pk, Decimal('0'))
                )

        result[cur] = {
            'prod_dia':    prod_dia,
            'prod_noche':  prod_noche,
            'tiene_dia':   tiene_dia,
            'tiene_noche': tiene_noche,
            'por_item':    por_item,
        }
        cur += timedelta(days=1)

    return result


# ─── INVENTARIO ───────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def inventario_lista(request):
    q = request.GET.get('q', '').strip()

    qs = (
        Item.objects
        .filter(activo=True)
        .select_related('categoria')
        .annotate(stock_calc=_STOCK_ANN)
        .order_by('orden', 'nombre')
    )
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(codigo__icontains=q))

    # Second query: principal location per item (max stock)
    stocks_raw = (
        Stock.objects
        .filter(item__in=qs)
        .values('item_id', 'ubicacion__nombre', 'cantidad_actual')
    )
    ub_map: dict = {}
    for s in stocks_raw:
        iid = s['item_id']
        if iid not in ub_map or s['cantidad_actual'] > ub_map[iid][0]:
            ub_map[iid] = (s['cantidad_actual'], s['ubicacion__nombre'])

    items_data = [
        {
            'item': item,
            'stock': item.stock_calc,
            'bajo': item.stock_calc <= item.stock_minimo,
            'ub_principal': ub_map.get(item.pk, (None, '–'))[1],
        }
        for item in qs
    ]

    context = {'items_data': items_data, 'q': q}
    return render(request, 'inventario/lista.html', context)


@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def item_detalle(request, pk):
    item = get_object_or_404(Item, pk=pk)
    stocks = Stock.objects.filter(item=item).select_related('ubicacion')
    # Últimas líneas que afectan este ítem (sin movimientos eliminados)
    detalles_recientes = (
        DetalleMovimiento.objects
        .filter(item=item, movimiento__eliminado=False)
        .select_related(
            'movimiento', 'movimiento__usuario',
            'ubicacion_origen', 'ubicacion_destino', 'cliente', 'maquina',
        )
        .order_by('-movimiento__fecha_movimiento')[:20]
    )
    context = {'item': item, 'stocks': stocks, 'detalles_recientes': detalles_recientes}
    return render(request, 'inventario/detalle.html', context)


@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def item_historial(request, pk):
    item = get_object_or_404(Item, pk=pk)
    tipo_filtro   = request.GET.get('tipo',   '').strip()
    estado_filtro = request.GET.get('estado', '').strip()

    # Líneas que afectan este ítem (kardex por detalle, con FK al movimiento cabecera)
    todos = list(
        DetalleMovimiento.objects
        .filter(item=item)
        .select_related(
            'movimiento',
            'movimiento__usuario',
            'movimiento__usuario_edicion',
            'movimiento__usuario_anulacion',
            'movimiento__usuario_eliminacion',
            'ubicacion_origen', 'ubicacion_destino',
            'cliente', 'maquina',
        )
        .order_by('movimiento__fecha_movimiento', 'movimiento__fecha', 'movimiento__pk', 'pk')
    )

    def _delta_activo(det):
        mov = det.movimiento
        if mov.anulado or mov.eliminado:
            return Decimal('0')
        t = mov.tipo_movimiento
        if t == 'entrada':
            return det.cantidad
        if t == 'salida':
            return -det.cantidad
        if t == 'ajuste':
            return det.cantidad
        return Decimal('0')

    kardex = []
    acum = Decimal('0')
    for det in todos:
        d = _delta_activo(det)
        stock_antes   = acum
        stock_despues = acum + d
        acum = stock_despues
        kardex.append({
            'det':          det,
            'mov':          det.movimiento,   # alias conveniente para la plantilla
            'delta':        d,
            'stock_antes':  stock_antes,
            'stock_despues': stock_despues,
            'afecta_stock': not (det.movimiento.anulado or det.movimiento.eliminado),
        })

    kardex.reverse()

    tipos_validos = ('entrada', 'salida', 'ajuste', 'transferencia')
    tipo_filtro_clean = tipo_filtro if tipo_filtro in tipos_validos else ''

    kardex_filtrado = kardex
    if tipo_filtro_clean:
        kardex_filtrado = [
            k for k in kardex_filtrado
            if k['mov'].tipo_movimiento == tipo_filtro_clean
        ]

    if estado_filtro == 'activos':
        kardex_filtrado = [
            k for k in kardex_filtrado
            if not k['mov'].anulado and not k['mov'].eliminado
        ]
    elif estado_filtro == 'anulados':
        kardex_filtrado = [k for k in kardex_filtrado if k['mov'].anulado]
    elif estado_filtro == 'eliminados':
        kardex_filtrado = [k for k in kardex_filtrado if k['mov'].eliminado]

    total_general    = len(kardex)
    total_activos    = sum(1 for k in kardex if not k['mov'].anulado and not k['mov'].eliminado)
    total_anulados   = sum(1 for k in kardex if k['mov'].anulado)
    total_eliminados = sum(1 for k in kardex if k['mov'].eliminado)

    paginator = Paginator(kardex_filtrado, 20)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'inventario/historial.html', {
        'item':             item,
        'page_obj':         page_obj,
        'tipo_filtro':      tipo_filtro_clean,
        'estado_filtro':    estado_filtro,
        'total':            len(kardex_filtrado),
        'total_general':    total_general,
        'total_activos':    total_activos,
        'total_anulados':   total_anulados,
        'total_eliminados': total_eliminados,
    })


@login_required
@permission_required(_perm('crear_item'), raise_exception=True)
def item_crear(request):
    if request.method == 'POST':
        form = ItemForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f'Ítem "{item.nombre}" creado exitosamente.')
            return redirect('item_detalle', pk=item.pk)
    else:
        form = ItemForm()

    categorias = Categoria.objects.all()
    return render(request, 'inventario/form.html', {
        'form': form, 'titulo': 'Nuevo Ítem', 'categorias': categorias
    })


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def item_editar(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if request.method == 'POST':
        form = ItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f'Ítem "{item.nombre}" actualizado.')
            return redirect('item_detalle', pk=item.pk)
    else:
        form = ItemForm(instance=item)

    return render(request, 'inventario/form.html', {
        'form': form, 'titulo': f'Editar: {item.nombre}', 'item': item
    })


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def item_toggle_activo(request, pk):
    item = get_object_or_404(Item, pk=pk)
    item.activo = not item.activo
    item.save()
    estado = 'activado' if item.activo else 'desactivado'
    messages.success(request, f'Ítem "{item.nombre}" {estado}.')
    return redirect('inventario_lista')


@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def ubicacion_lista(request):
    ubicaciones = Ubicacion.objects.all()
    return render(request, 'inventario/ubicaciones.html', {'ubicaciones': ubicaciones})


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def ubicacion_crear(request):
    if request.method == 'POST':
        form = UbicacionForm(request.POST)
        if form.is_valid():
            u = form.save()
            messages.success(request, f'Ubicación "{u.nombre}" creada.')
            return redirect('ubicacion_lista')
    else:
        form = UbicacionForm()
    return render(request, 'inventario/ubicacion_form.html', {
        'form': form, 'titulo': 'Nueva Ubicación'
    })


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def ubicacion_editar(request, pk):
    ubicacion = get_object_or_404(Ubicacion, pk=pk)
    if request.method == 'POST':
        form = UbicacionForm(request.POST, instance=ubicacion)
        if form.is_valid():
            form.save()
            messages.success(request, f'Ubicación "{ubicacion.nombre}" actualizada.')
            return redirect('ubicacion_lista')
    else:
        form = UbicacionForm(instance=ubicacion)
    return render(request, 'inventario/ubicacion_form.html', {
        'form': form, 'titulo': f'Editar: {ubicacion.nombre}', 'ubicacion': ubicacion
    })


# ─── MOVIMIENTOS ──────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def movimiento_lista(request):
    form = FiltroMovimientosForm(request.GET or None)
    movimientos = (
        MovimientoInventario.objects
        .prefetch_related('detalles__item', 'detalles__ubicacion_origen',
                          'detalles__ubicacion_destino', 'detalles__cliente',
                          'detalles__maquina')
        .select_related('usuario', 'usuario_anulacion', 'usuario_edicion',
                        'usuario_eliminacion', 'cliente')
        .annotate(
            num_detalles=Count('detalles', distinct=True),
            num_pendientes=Count(
                'detalles',
                filter=Q(detalles__pendiente_conciliacion=True),
                distinct=True,
            ),
        )
        .order_by('-fecha_movimiento')
    )

    if form.is_valid():
        if form.cleaned_data.get('fecha_inicio'):
            movimientos = movimientos.filter(
                fecha_movimiento__date__gte=form.cleaned_data['fecha_inicio']
            )
        if form.cleaned_data.get('fecha_fin'):
            movimientos = movimientos.filter(
                fecha_movimiento__date__lte=form.cleaned_data['fecha_fin']
            )
        if form.cleaned_data.get('tipo_movimiento'):
            movimientos = movimientos.filter(
                tipo_movimiento=form.cleaned_data['tipo_movimiento']
            )
        if form.cleaned_data.get('item'):
            movimientos = movimientos.filter(
                detalles__item=form.cleaned_data['item']
            ).distinct()

    if request.GET.get('export') == 'csv':
        return _exportar_movimientos_csv(movimientos)

    paginator = Paginator(movimientos, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'movimientos/lista.html', {
        'movimientos': page_obj,
        'page_obj': page_obj,
        'form': form,
    })


def _exportar_movimientos_csv(movimientos):
    """Exporta cada LÍNEA (DetalleMovimiento) como una fila CSV, con datos del cabecera."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="movimientos.csv"'
    response.write('﻿')  # BOM para Excel
    writer = csv.writer(response)
    writer.writerow([
        'Movimiento #', 'Fecha Movimiento', 'Fecha Registro', 'Tipo',
        'Ítem', 'Código', 'Cantidad', 'Unidad',
        'Origen', 'Destino', 'Cliente', 'Máquina', 'Motivo', 'Usuario',
        'Estado',
    ])
    for mov in movimientos:
        estado = ('Anulado' if mov.anulado else
                  'Eliminado' if mov.eliminado else
                  'Editado' if mov.editado else 'Activo')
        for det in mov.detalles.select_related(
            'item', 'ubicacion_origen', 'ubicacion_destino', 'cliente', 'maquina'
        ).all():
            writer.writerow([
                mov.pk,
                mov.fecha_movimiento.strftime('%Y-%m-%d %H:%M'),
                mov.fecha.strftime('%Y-%m-%d %H:%M'),
                mov.get_tipo_movimiento_display(),
                det.item.nombre,
                det.item.codigo,
                det.cantidad,
                det.item.unidad_medida,
                det.ubicacion_origen.nombre if det.ubicacion_origen else '',
                det.ubicacion_destino.nombre if det.ubicacion_destino else '',
                det.cliente.nombre if det.cliente else '',
                det.maquina.nombre if det.maquina else '',
                mov.motivo,
                mov.usuario.get_full_name() or mov.usuario.username,
                estado,
            ])
    return response


@login_required
@permission_required(_perm('registrar_entrada'), raise_exception=True)
def movimiento_entrada(request):
    items = Item.objects.filter(activo=True).order_by('orden', 'nombre')
    ubicaciones = Ubicacion.objects.all()
    item_id_inicial = request.GET.get('item', '')

    items_json = json.dumps([
        {'pk': it.pk, 'nombre': it.nombre, 'codigo': it.codigo, 'unidad': it.unidad_medida}
        for it in items
    ])
    ubicaciones_json = json.dumps([
        {'pk': u.pk, 'nombre': u.nombre, 'tipo': u.get_tipo_display()}
        for u in ubicaciones
    ])

    if request.method == 'POST':
        ubicacion_destino_id = request.POST.get('ubicacion_destino', '').strip()
        motivo = request.POST.get('motivo', '')
        fecha_mov_str = request.POST.get('fecha_movimiento', '').strip()
        item_ids = request.POST.getlist('item[]')
        cantidades = request.POST.getlist('cantidad[]')

        errores = []
        ubicacion_destino = None

        try:
            ubicacion_destino = Ubicacion.objects.get(pk=ubicacion_destino_id)
        except (Ubicacion.DoesNotExist, ValueError):
            errores.append('Debes seleccionar una ubicación de destino.')

        fecha_movimiento = timezone.now()
        if fecha_mov_str:
            try:
                from django.utils.dateparse import parse_datetime
                parsed = parse_datetime(fecha_mov_str)
                if parsed:
                    fecha_movimiento = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
            except Exception:
                pass

        filas_validas = []
        for i, (item_id, cant_str) in enumerate(zip(item_ids, cantidades), 1):
            cant_str = cant_str.strip()
            if not item_id and not cant_str:
                continue
            if not item_id:
                errores.append(f'Fila {i}: selecciona un ítem.')
                continue
            if not cant_str:
                errores.append(f'Fila {i}: ingresa una cantidad.')
                continue
            try:
                cantidad = Decimal(cant_str)
                if cantidad <= 0:
                    raise ValueError
            except (ValueError, Exception):
                errores.append(f'Fila {i}: cantidad inválida.')
                continue
            try:
                item = Item.objects.get(pk=item_id, activo=True)
            except Item.DoesNotExist:
                errores.append(f'Fila {i}: ítem no encontrado.')
                continue
            filas_validas.append((item, cantidad))

        if not filas_validas and not errores:
            errores.append('Agrega al menos un ítem con cantidad.')

        if errores:
            for e in errores:
                messages.error(request, e)
            filas_previas = [
                {'item_id': iid, 'cantidad': cant}
                for iid, cant in zip(item_ids, cantidades)
                if iid or cant.strip()
            ]
            return render(request, 'movimientos/entrada.html', {
                'items_json': items_json,
                'ubicaciones_json': ubicaciones_json,
                'item_id_inicial': item_id_inicial,
                'ub_destino_previo': ubicacion_destino_id,
                'motivo_previo': motivo,
                'fecha_mov_previo': fecha_mov_str,
                'filas_previas_json': json.dumps(filas_previas),
            })

        with transaction.atomic():
            mov = MovimientoInventario.objects.create(
                tipo_movimiento='entrada',
                motivo=motivo,
                fecha_movimiento=fecha_movimiento,
                usuario=request.user,
            )
            for item, cantidad in filas_validas:
                det = DetalleMovimiento.objects.create(
                    movimiento=mov,
                    item=item,
                    cantidad=cantidad,
                    ubicacion_destino=ubicacion_destino,
                )
                _aplicar_efecto_detalle(det)
                send_event('movement_created', {
                    'tipo': 'entrada', 'item': item.nombre, 'codigo': item.codigo,
                    'cantidad': str(cantidad), 'ubicacion': ubicacion_destino.nombre,
                    'usuario': request.user.username,
                })
                notify_stock(item, movimiento='entrada', usuario=request.user.username)
        messages.success(
            request,
            f'Movimiento #{mov.pk} registrado con {len(filas_validas)} ítem(s).'
        )
        return redirect('movimiento_detalle', pk=mov.pk)

    return render(request, 'movimientos/entrada.html', {
        'items_json': items_json,
        'ubicaciones_json': ubicaciones_json,
        'item_id_inicial': item_id_inicial,
        'filas_previas_json': '[]',
    })


@login_required
@permission_required(_perm('registrar_salida'), raise_exception=True)
def movimiento_salida(request):
    """
    Registro de salidas con cuatro tabs:

    • Producto Terminado  — filas dinámicas (usuario agrega solo los necesarios),
                           dropdown filtrado a productos, orden por item.orden,
                           cliente a nivel de cabecera, permite stock negativo
                           (marca pendiente_conciliacion=True en cada línea).
                           Usa campos item_pt[] y cantidad_pt[] para evitar
                           colisión con los tabs de filas dinámicas (item[], cantidad[]).
    • Repuestos           — filas dinámicas, bloquea si stock insuficiente.
    • Consumibles         — filas dinámicas, bloquea si stock insuficiente.
    • Otros               — filas dinámicas, bloquea si stock insuficiente.
    """
    from django.utils.dateparse import parse_datetime

    # ── Datos maestros ────────────────────────────────────────────────────────
    items_producto   = list(Item.objects.filter(activo=True, tipo='producto')
                            .order_by('orden', 'nombre'))
    items_repuesto   = list(Item.objects.filter(activo=True, tipo='repuesto')
                            .order_by('orden', 'nombre'))
    items_consumible = list(Item.objects.filter(activo=True, tipo='consumible')
                            .order_by('orden', 'nombre'))
    items_otros      = list(Item.objects.filter(activo=True)
                            .exclude(tipo__in=['producto', 'repuesto', 'consumible'])
                            .order_by('orden', 'nombre'))

    ubicaciones = list(Ubicacion.objects.all().order_by('nombre'))
    clientes    = list(Cliente.objects.filter(activo=True).order_by('nombre'))
    maquinas    = list(Maquina.objects.filter(activo=True).order_by('nombre'))

    # ── Stock por item {item_pk: {ub_pk: stock_actual}} ───────────────────────
    stocks_qs = Stock.objects.select_related('item', 'ubicacion').all()
    stocks_por_item = {}
    for s in stocks_qs:
        stocks_por_item.setdefault(s.item_id, {})[s.ubicacion_id] = float(s.cantidad_actual)

    # ── JSON para JavaScript ──────────────────────────────────────────────────
    def _items_json(lst):
        return json.dumps([
            {'pk': it.pk, 'nombre': it.nombre, 'codigo': it.codigo,
             'tipo': it.tipo, 'unidad': it.unidad_medida}
            for it in lst
        ])

    ubicaciones_json = json.dumps([
        {'pk': u.pk, 'nombre': u.nombre, 'tipo': u.get_tipo_display()}
        for u in ubicaciones
    ])
    clientes_json = json.dumps([
        {'pk': c.pk, 'nombre': c.nombre} for c in clientes
    ])
    maquinas_json = json.dumps([
        {'pk': m.pk, 'nombre': m.nombre} for m in maquinas
    ])
    stocks_json = json.dumps(stocks_por_item)

    def _parse_fecha(fecha_str):
        if not fecha_str:
            return timezone.now()
        try:
            parsed = parse_datetime(fecha_str.strip())
            if parsed:
                return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
        except Exception:
            pass
        return timezone.now()

    # ── Contexto base (GET y re-render en error) ───────────────────────────────
    def _ctx(extra=None):
        ctx = {
            'items_producto_json':   _items_json(items_producto),
            'items_repuesto_json':   _items_json(items_repuesto),
            'items_consumible_json': _items_json(items_consumible),
            'items_otros_json':      _items_json(items_otros),
            'ubicaciones_json':      ubicaciones_json,
            'clientes_json':         clientes_json,
            'maquinas_json':         maquinas_json,
            'stocks_json':           stocks_json,
            'ubicaciones':           ubicaciones,
            'clientes':              clientes,
        }
        if extra:
            ctx.update(extra)
        return ctx

    if request.method != 'POST':
        tab_inicial = request.GET.get('tab', 'producto_terminado')
        item_id_inicial = request.GET.get('item', '')
        return render(request, 'movimientos/salida.html',
                      _ctx({'tab_inicial': tab_inicial,
                            'item_id_inicial': item_id_inicial,
                            'filas_pt_previas_json': '[]',
                            'filas_previas_json': '[]'}))

    # ═══════════════════════════════════════════════════════════════════════════
    # POST
    # ═══════════════════════════════════════════════════════════════════════════
    tipo_salida   = request.POST.get('tipo_salida', 'producto_terminado')
    motivo        = request.POST.get('motivo', '').strip()
    fecha_mov_str = request.POST.get('fecha_movimiento', '')
    fecha_movimiento = _parse_fecha(fecha_mov_str)

    errores      = []
    filas_validas = []   # (item, cantidad, ubicacion, pendiente, maquina)

    # ── TAB: Producto Terminado ────────────────────────────────────────────────
    if tipo_salida == 'producto_terminado':
        cliente_id  = request.POST.get('cliente_header', '').strip()
        ub_pt_id    = request.POST.get('ubicacion_origen_pt', '').strip()

        # Filas dinámicas PT usan nombres distintos (item_pt[], cantidad_pt[])
        # para evitar colisión con los tabs de rep/con/otros (item[], cantidad[])
        item_ids_pt  = request.POST.getlist('item_pt[]')
        cantidades_pt = request.POST.getlist('cantidad_pt[]')

        cliente = None
        if not cliente_id:
            errores.append('Selecciona un cliente.')
        else:
            try:
                cliente = Cliente.objects.get(pk=cliente_id)
            except Cliente.DoesNotExist:
                errores.append('Cliente no encontrado.')

        ubicacion_pt = None
        if not ub_pt_id:
            errores.append('Selecciona la ubicación de origen.')
        else:
            try:
                ubicacion_pt = Ubicacion.objects.get(pk=ub_pt_id)
            except Ubicacion.DoesNotExist:
                errores.append('Ubicación no encontrada.')

        items_producto_map = {str(it.pk): it for it in items_producto}
        for i, (item_id, cant_str) in enumerate(zip(item_ids_pt, cantidades_pt), 1):
            cant_str = cant_str.strip()
            if not item_id and not cant_str:
                continue
            if not item_id:
                errores.append(f'Fila {i}: selecciona un producto.')
                continue
            if not cant_str:
                errores.append(f'Fila {i}: ingresa una cantidad.')
                continue
            try:
                cantidad = Decimal(cant_str)
                if cantidad <= 0:
                    raise ValueError
            except (ValueError, Exception):
                errores.append(f'Fila {i}: cantidad inválida.')
                continue
            it = items_producto_map.get(str(item_id))
            if not it:
                errores.append(f'Fila {i}: producto no encontrado.')
                continue
            filas_validas.append((it, cantidad, None, True, None))

        if not filas_validas and not errores:
            errores.append('Agrega al menos un producto con cantidad.')

        if errores:
            for e in errores:
                messages.error(request, e)
            filas_pt_previas = [
                {'item_id': iid, 'cantidad': cant}
                for iid, cant in zip(item_ids_pt, cantidades_pt)
                if iid or cant.strip()
            ]
            return render(request, 'movimientos/salida.html',
                          _ctx({'tab_inicial': 'producto_terminado',
                                'motivo_previo': motivo,
                                'fecha_mov_previo': fecha_mov_str,
                                'cliente_previo': cliente_id,
                                'ub_pt_previo': ub_pt_id,
                                'filas_pt_previas_json': json.dumps(filas_pt_previas),
                                'filas_previas_json': '[]'}))

        # Todo OK → guardar
        with transaction.atomic():
            mov = MovimientoInventario.objects.create(
                tipo_movimiento='salida',
                tipo_salida='producto_terminado',
                motivo=motivo,
                fecha_movimiento=fecha_movimiento,
                usuario=request.user,
                cliente=cliente,
            )
            pendientes_creados = []
            for it, cantidad, _, _pendiente, _maq in filas_validas:
                # Calcular si habrá stock negativo
                stock_ub = Stock.objects.filter(item=it, ubicacion=ubicacion_pt).first()
                stock_actual = stock_ub.cantidad_actual if stock_ub else Decimal('0')
                pendiente = stock_actual < cantidad

                det = DetalleMovimiento.objects.create(
                    movimiento=mov,
                    item=it,
                    cantidad=cantidad,
                    ubicacion_origen=ubicacion_pt,
                    cliente=cliente,
                    pendiente_conciliacion=pendiente,
                )
                _aplicar_efecto_detalle(det)
                if pendiente:
                    pendientes_creados.append(det)
                send_event('movement_created', {
                    'tipo': 'salida', 'item': it.nombre, 'codigo': it.codigo,
                    'cantidad': str(cantidad), 'ubicacion': ubicacion_pt.nombre,
                    'cliente': cliente.nombre if cliente else None,
                    'pendiente_conciliacion': pendiente,
                    'usuario': request.user.username,
                })
                notify_stock(it, movimiento='salida', usuario=request.user.username)

            # Notificar pendientes
            for det in pendientes_creados:
                send_event('salida_pendiente_conciliacion', {
                    'movimiento_pk': mov.pk,
                    'item': det.item.nombre, 'codigo': det.item.codigo,
                    'cantidad': str(det.cantidad),
                    'ubicacion': ubicacion_pt.nombre,
                    'cliente': cliente.nombre,
                    'usuario': request.user.username,
                })

        n_pendientes = len(pendientes_creados)
        msg = f'Movimiento #{mov.pk} registrado con {len(filas_validas)} ítem(s).'
        if n_pendientes:
            msg += f' ⚠️ {n_pendientes} línea(s) con stock insuficiente marcada(s) como pendiente(s) de conciliación.'
        messages.success(request, msg)
        return redirect('movimiento_detalle', pk=mov.pk)

    # ── TABS: Repuestos / Consumibles / Otros (filas dinámicas) ───────────────
    item_ids      = request.POST.getlist('item[]')
    cantidades    = request.POST.getlist('cantidad[]')
    ubicacion_ids = request.POST.getlist('ubicacion_origen[]')
    maquina_ids   = request.POST.getlist('maquina[]')

    all_items_qs = {str(it.pk): it for it in
                    Item.objects.filter(activo=True)
                    .exclude(tipo='producto')}

    for i, (item_id, cant_str, ub_id, maq_id) in enumerate(
        zip(item_ids, cantidades, ubicacion_ids, maquina_ids), 1
    ):
        cant_str = cant_str.strip()
        if not item_id and not cant_str:
            continue
        if not item_id:
            errores.append(f'Fila {i}: selecciona un ítem.')
            continue
        if not cant_str:
            errores.append(f'Fila {i}: ingresa una cantidad.')
            continue
        try:
            cantidad = Decimal(cant_str)
            if cantidad <= 0:
                raise ValueError
        except (ValueError, Exception):
            errores.append(f'Fila {i}: cantidad inválida.')
            continue

        item = all_items_qs.get(str(item_id))
        if not item:
            errores.append(f'Fila {i}: ítem no encontrado.')
            continue

        if not ub_id:
            errores.append(f'Fila {i} ({item.nombre}): selecciona ubicación de origen.')
            continue
        try:
            ubicacion = Ubicacion.objects.get(pk=ub_id)
        except Ubicacion.DoesNotExist:
            errores.append(f'Fila {i}: ubicación no encontrada.')
            continue

        # Bloquear si stock insuficiente (repuestos/consumibles/otros)
        try:
            stock = Stock.objects.get(item=item, ubicacion=ubicacion)
            if stock.cantidad_actual < cantidad:
                errores.append(
                    f'Fila {i} ({item.nombre}): stock insuficiente. '
                    f'Disponible: {stock.cantidad_actual} {item.unidad_medida}.'
                )
                continue
        except Stock.DoesNotExist:
            errores.append(f'Fila {i} ({item.nombre}): no hay stock en esa ubicación.')
            continue

        maquina = None
        if maq_id:
            try:
                maquina = Maquina.objects.get(pk=maq_id)
            except Maquina.DoesNotExist:
                pass

        # Repuesto requiere máquina
        if item.tipo == 'repuesto' and not maquina:
            errores.append(f'Fila {i} ({item.nombre}): selecciona una máquina.')
            continue

        filas_validas.append((item, cantidad, ubicacion, False, maquina))

    if not filas_validas and not errores:
        errores.append('Agrega al menos un ítem con cantidad.')

    if errores:
        for e in errores:
            messages.error(request, e)
        filas_previas = [
            {'item_id': iid, 'cantidad': cant, 'ub_id': ub, 'maq_id': maq}
            for iid, cant, ub, maq
            in zip(item_ids, cantidades, ubicacion_ids, maquina_ids)
            if iid or cant.strip()
        ]
        return render(request, 'movimientos/salida.html',
                      _ctx({'tab_inicial': tipo_salida,
                            'motivo_previo': motivo,
                            'fecha_mov_previo': fecha_mov_str,
                            'filas_previas_json': json.dumps(filas_previas)}))

    with transaction.atomic():
        mov = MovimientoInventario.objects.create(
            tipo_movimiento='salida',
            tipo_salida=tipo_salida,
            motivo=motivo,
            fecha_movimiento=fecha_movimiento,
            usuario=request.user,
        )
        for it, cantidad, ubicacion, _pendiente, maquina in filas_validas:
            det = DetalleMovimiento.objects.create(
                movimiento=mov,
                item=it,
                cantidad=cantidad,
                ubicacion_origen=ubicacion,
                maquina=maquina,
            )
            _aplicar_efecto_detalle(det)
            send_event('movement_created', {
                'tipo': 'salida', 'item': it.nombre, 'codigo': it.codigo,
                'cantidad': str(cantidad), 'ubicacion': ubicacion.nombre,
                'usuario': request.user.username,
            })
            notify_stock(it, movimiento='salida', usuario=request.user.username)

    messages.success(
        request,
        f'Movimiento #{mov.pk} registrado con {len(filas_validas)} ítem(s).'
    )
    return redirect('movimiento_detalle', pk=mov.pk)


@login_required
@permission_required(_perm('registrar_entrada'), raise_exception=True)
def movimiento_transferencia(request):
    if request.method == 'POST':
        form = MovimientoTransferenciaForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                mov = MovimientoInventario.objects.create(
                    tipo_movimiento='transferencia',
                    motivo=form.cleaned_data.get('motivo', ''),
                    usuario=request.user,
                )
                det = DetalleMovimiento.objects.create(
                    movimiento=mov,
                    item=form.cleaned_data['item'],
                    cantidad=form.cleaned_data['cantidad'],
                    ubicacion_origen=form.cleaned_data['ubicacion_origen'],
                    ubicacion_destino=form.cleaned_data['ubicacion_destino'],
                )
                _aplicar_efecto_detalle(det)
            messages.success(request, f'Transferencia registrada (Movimiento #{mov.pk}).')
            return redirect('movimiento_detalle', pk=mov.pk)
    else:
        form = MovimientoTransferenciaForm()

    return render(request, 'movimientos/transferencia.html', {'form': form})


# ─── DETALLE / GESTIÓN DE MOVIMIENTOS ────────────────────────────────────────

@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def movimiento_detalle(request, pk):
    """Vista de detalle de un Movimiento (cabecera + líneas)."""
    mov = get_object_or_404(
        MovimientoInventario.objects.select_related(
            'usuario', 'usuario_edicion', 'usuario_anulacion', 'usuario_eliminacion'
        ).prefetch_related(
            'detalles__item', 'detalles__ubicacion_origen',
            'detalles__ubicacion_destino', 'detalles__cliente', 'detalles__maquina',
        ),
        pk=pk,
    )
    return render(request, 'movimientos/detalle.html', {'mov': mov})


@login_required
@permission_required(_perm('editar_movimiento'), raise_exception=True)
def movimiento_editar(request, pk):
    """
    Edita un movimiento existente.
    Permite cambiar la fecha, motivo y las cantidades/ubicaciones por línea.
    Flujo: revertir todos los detalles → guardar cambios → re-aplicar detalles.
    Todo en transaction.atomic().
    """
    mov = get_object_or_404(
        MovimientoInventario.objects.prefetch_related(
            'detalles__item', 'detalles__ubicacion_origen',
            'detalles__ubicacion_destino', 'detalles__cliente', 'detalles__maquina',
        ).select_related('usuario'),
        pk=pk,
    )

    if not _movimiento_editable(mov):
        messages.error(request, 'Este movimiento está anulado o eliminado y no puede editarse.')
        return redirect('movimiento_detalle', pk=pk)

    ubicaciones = Ubicacion.objects.all()
    clientes    = Cliente.objects.filter(activo=True).order_by('nombre')
    maquinas    = Maquina.objects.filter(activo=True).order_by('nombre')

    if request.method == 'POST':
        motivo_edicion = request.POST.get('motivo_edicion', '').strip()
        nuevo_motivo   = request.POST.get('motivo', mov.motivo)
        nueva_fecha_str = request.POST.get('fecha_movimiento', '').strip()

        if not motivo_edicion:
            messages.error(request, 'El motivo de edición es obligatorio.')
        else:
            nueva_fecha = mov.fecha_movimiento
            if nueva_fecha_str:
                from django.utils.dateparse import parse_datetime
                parsed = parse_datetime(nueva_fecha_str)
                if parsed:
                    nueva_fecha = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed

            # Recoger nuevas cantidades por detalle
            det_cantidades   = request.POST.getlist('det_cantidad[]')
            det_ids          = request.POST.getlist('det_id[]')
            det_ub_origen    = request.POST.getlist('det_ub_origen[]')
            det_ub_destino   = request.POST.getlist('det_ub_destino[]')

            errores = []
            nuevos_valores = []
            detalles = list(mov.detalles.all())

            for i, det in enumerate(detalles):
                cant_str = det_cantidades[i].strip() if i < len(det_cantidades) else ''
                try:
                    nueva_cant = Decimal(cant_str)
                    if nueva_cant <= 0:
                        raise ValueError
                except Exception:
                    errores.append(f'Línea {i+1} ({det.item.nombre}): cantidad inválida.')
                    continue

                ub_or_id  = det_ub_origen[i]  if i < len(det_ub_origen)  else ''
                ub_dst_id = det_ub_destino[i] if i < len(det_ub_destino) else ''
                nueva_ub_origen  = Ubicacion.objects.filter(pk=ub_or_id).first()  if ub_or_id  else None
                nueva_ub_destino = Ubicacion.objects.filter(pk=ub_dst_id).first() if ub_dst_id else None
                nuevos_valores.append((det, nueva_cant, nueva_ub_origen, nueva_ub_destino))

            if errores:
                for e in errores:
                    messages.error(request, e)
            else:
                with transaction.atomic():
                    # 1. Revertir todos los detalles originales
                    _revertir_todos_los_detalles(mov)
                    # 2. Actualizar cabecera
                    mov.motivo           = nuevo_motivo
                    mov.fecha_movimiento = nueva_fecha
                    mov.editado          = True
                    mov.fecha_edicion    = timezone.now()
                    mov.usuario_edicion  = request.user
                    mov.motivo_edicion   = motivo_edicion
                    mov.save(update_fields=[
                        'motivo', 'fecha_movimiento',
                        'editado', 'fecha_edicion', 'usuario_edicion', 'motivo_edicion',
                    ])
                    # 3. Actualizar detalles y re-aplicar stock
                    for det, nueva_cant, nueva_ub_origen, nueva_ub_destino in nuevos_valores:
                        det.cantidad          = nueva_cant
                        det.ubicacion_origen  = nueva_ub_origen
                        det.ubicacion_destino = nueva_ub_destino
                        det.save(update_fields=['cantidad', 'ubicacion_origen', 'ubicacion_destino'])
                        _aplicar_efecto_detalle(det)
                        notify_stock(det.item, movimiento='edicion', usuario=request.user.username)

                security_log.info(
                    'Movimiento #%s editado por %s — %s',
                    mov.pk, request.user.username, motivo_edicion,
                )
                messages.success(request, f'Movimiento #{mov.pk} editado correctamente.')
                return redirect('movimiento_detalle', pk=mov.pk)

    return render(request, 'movimientos/editar.html', {
        'mov': mov,
        'ubicaciones': ubicaciones,
        'clientes': clientes,
        'maquinas': maquinas,
    })


@login_required
@permission_required(_perm('anular_movimiento'), raise_exception=True)
def movimiento_anular(request, pk):
    """
    Anula un movimiento completo: revierte el stock de TODOS sus detalles y
    marca la cabecera como anulada. No lo borra — queda visible con badge «Anulado».
    """
    mov = get_object_or_404(
        MovimientoInventario.objects.prefetch_related(
            'detalles__item', 'detalles__ubicacion_origen', 'detalles__ubicacion_destino'
        ).select_related('usuario'),
        pk=pk,
    )

    if mov.anulado:
        messages.warning(request, 'Este movimiento ya estaba anulado.')
        return redirect('movimiento_detalle', pk=pk)
    if mov.eliminado:
        messages.error(request, 'No se puede anular un movimiento eliminado.')
        return redirect('movimiento_detalle', pk=pk)

    if request.method == 'POST':
        motivo = request.POST.get('motivo_anulacion', '').strip()
        if not motivo:
            messages.error(request, 'El motivo de anulación es obligatorio.')
        else:
            with transaction.atomic():
                _revertir_todos_los_detalles(mov)
                mov.anulado           = True
                mov.fecha_anulacion   = timezone.now()
                mov.usuario_anulacion = request.user
                mov.motivo_anulacion  = motivo
                mov.save(update_fields=[
                    'anulado', 'fecha_anulacion', 'usuario_anulacion', 'motivo_anulacion'
                ])
                for det in mov.detalles.select_related('item').all():
                    notify_stock(det.item, movimiento='anulacion', usuario=request.user.username)

            security_log.info(
                'Movimiento #%s ANULADO por %s — %s',
                mov.pk, request.user.username, motivo,
            )
            messages.success(
                request,
                f'Movimiento #{mov.pk} anulado. Stock revertido en {mov.detalles.count()} ítem(s).'
            )
            return redirect('movimiento_lista')

    return render(request, 'movimientos/anular.html', {'mov': mov})


@login_required
@permission_required(_perm('eliminar_movimiento'), raise_exception=True)
def movimiento_eliminar(request, pk):
    """
    Eliminación lógica de un movimiento.
    Si no estaba anulado, revierte el stock de todos sus detalles.
    Requiere doble confirmación y motivo.
    """
    mov = get_object_or_404(
        MovimientoInventario.objects.prefetch_related(
            'detalles__item', 'detalles__ubicacion_origen', 'detalles__ubicacion_destino'
        ).select_related('usuario'),
        pk=pk,
    )

    if mov.eliminado:
        messages.warning(request, 'Este movimiento ya estaba eliminado.')
        return redirect('movimiento_lista')

    if mov.anulado and not request.user.is_superuser:
        messages.error(request, 'Solo un superusuario puede eliminar un movimiento ya anulado.')
        return redirect('movimiento_detalle', pk=pk)

    if request.method == 'POST':
        confirmacion = request.POST.get('confirmacion', '').strip()
        motivo = request.POST.get('motivo_eliminacion', '').strip()

        if confirmacion != 'ELIMINAR':
            messages.error(request, 'Escribe ELIMINAR en el campo de confirmación.')
        elif not motivo:
            messages.error(request, 'El motivo de eliminación es obligatorio.')
        else:
            with transaction.atomic():
                # Solo revertir si no estaba ya anulado (el anulado ya lo revirtió)
                if not mov.anulado:
                    _revertir_todos_los_detalles(mov)
                mov.eliminado           = True
                mov.fecha_eliminacion   = timezone.now()
                mov.usuario_eliminacion = request.user
                mov.motivo_eliminacion  = motivo
                mov.save(update_fields=[
                    'eliminado', 'fecha_eliminacion', 'usuario_eliminacion', 'motivo_eliminacion'
                ])
                if not mov.anulado:
                    for det in mov.detalles.select_related('item').all():
                        notify_stock(det.item, movimiento='eliminacion',
                                     usuario=request.user.username)

            security_log.warning(
                'Movimiento #%s ELIMINADO por %s — %s',
                mov.pk, request.user.username, motivo,
            )
            messages.success(request, f'Movimiento #{mov.pk} eliminado lógicamente.')
            return redirect('movimiento_lista')

    return render(request, 'movimientos/eliminar.html', {'mov': mov})


# ─── CONTEOS ──────────────────────────────────────────────────────────────────

@login_required
def conteo_anular(request, pk):
    """
    Anulación lógica de un conteo: revierte en stock todos los ajustes de
    conciliación generados por este conteo, marca cada movimiento de ajuste
    como anulado, y finalmente marca el conteo como anulado.
    No elimina ningún registro.
    """
    if not (request.user.has_perm(_perm('anular_conteo')) or request.user.is_staff):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    conteo = get_object_or_404(
        Conteo.objects.select_related('usuario'),
        pk=pk,
    )

    if conteo.anulado:
        messages.warning(request, 'Este conteo ya estaba anulado.')
        return redirect('conteo_detalle', pk=pk)

    # Movimientos de ajuste vinculados a este conteo (por motivo)
    ajustes_qs = (
        MovimientoInventario.objects
        .filter(
            tipo_movimiento='ajuste',
            motivo__contains=f'Conteo #{conteo.pk}',
            anulado=False,
            eliminado=False,
        )
        .prefetch_related(
            'detalles__item',
            'detalles__ubicacion_origen',
            'detalles__ubicacion_destino',
        )
    )
    ajustes = list(ajustes_qs)

    if request.method == 'POST':
        motivo = request.POST.get('motivo_anulacion', '').strip()
        if not motivo:
            messages.error(request, 'El motivo de anulación es obligatorio.')
        else:
            ahora = timezone.now()
            with transaction.atomic():
                for mov_ajuste in ajustes:
                    _revertir_todos_los_detalles(mov_ajuste)
                    mov_ajuste.anulado           = True
                    mov_ajuste.fecha_anulacion   = ahora
                    mov_ajuste.usuario_anulacion = request.user
                    mov_ajuste.motivo_anulacion  = f'Anulación de Conteo #{conteo.pk} — {motivo}'
                    mov_ajuste.save(update_fields=[
                        'anulado', 'fecha_anulacion', 'usuario_anulacion', 'motivo_anulacion',
                    ])
                    for det in mov_ajuste.detalles.select_related('item').all():
                        notify_stock(det.item, movimiento='anulacion', usuario=request.user.username)

                conteo.anulado           = True
                conteo.fecha_anulacion   = ahora
                conteo.usuario_anulacion = request.user
                conteo.motivo_anulacion  = motivo
                conteo.save(update_fields=[
                    'anulado', 'fecha_anulacion', 'usuario_anulacion', 'motivo_anulacion',
                ])

            security_log.info(
                'Conteo #%s ANULADO por %s — %s ajuste(s) revertido(s) — %s',
                conteo.pk, request.user.username, len(ajustes), motivo,
            )
            messages.success(
                request,
                f'Conteo #{conteo.pk} anulado. {len(ajustes)} ajuste(s) de conciliación revertido(s).'
            )
            return redirect('conteo_lista')

    return render(request, 'conteos/anular.html', {
        'conteo': conteo,
        'ajustes': ajustes,
    })


@login_required
@permission_required(_perm('registrar_conteo'), raise_exception=True)
def conteo_lista(request):
    qs = (
        Conteo.objects
        .select_related('usuario')
        .annotate(num_detalles=Count('detalles'))
        .order_by('-fecha', 'turno')
    )
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'conteos/lista.html', {'conteos': page_obj, 'page_obj': page_obj})


@login_required
@permission_required(_perm('registrar_conteo'), raise_exception=True)
def conteo_nuevo(request):
    hoy = date.today()
    ubicaciones = list(Ubicacion.objects.all())

    stocks_map = {}
    for s in Stock.objects.select_related('item', 'ubicacion').filter(item__activo=True):
        stocks_map[(s.item_id, s.ubicacion_id)] = s.cantidad_actual

    stocks_totales = {}
    for s in Stock.objects.filter(item__activo=True).values('item_id').annotate(t=Sum('cantidad_actual')):
        stocks_totales[s['item_id']] = s['t'] or Decimal('0')

    all_items = list(
        Item.objects.filter(activo=True)
        .select_related('categoria')
        .order_by('orden', 'nombre')
    )

    def _clasificar(item):
        cat = (item.categoria.nombre if item.categoria else '').lower()
        nom = item.nombre.lower()
        if item.tipo == 'producto' and ('camiseta' in cat or 'camiseta' in nom):
            return 'camiseta'
        if item.tipo == 'consumible' and ('pigment' in cat or 'pigment' in nom):
            return 'pigmentos'
        if item.tipo == 'producto' and ('lisa' in cat or 'lisa' in nom):
            return 'lisa'
        return 'otros'

    def _build_item_dict(item):
        stocks_by_ub = {
            str(upk): str(qty)
            for (ipk, upk), qty in stocks_map.items()
            if ipk == item.pk
        }
        best_ub = max(stocks_by_ub, key=lambda k: Decimal(stocks_by_ub[k]), default=None)
        return {
            'pk': item.pk,
            'nombre': item.nombre,
            'codigo': item.codigo,
            'categoria': item.categoria.nombre if item.categoria else '',
            'unidad': item.unidad_medida,
            'stock_total': str(stocks_totales.get(item.pk, Decimal('0'))),
            'default_ub': int(best_ub) if best_ub else (ubicaciones[0].pk if ubicaciones else None),
            'stocks_by_ub': stocks_by_ub,
        }

    items_por_tipo = {'camiseta': [], 'pigmentos': [], 'lisa': [], 'otros': []}
    for item in all_items:
        items_por_tipo[_clasificar(item)].append(_build_item_dict(item))

    items_por_tipo_json = json.dumps(items_por_tipo)
    all_items_json = json.dumps([_build_item_dict(item) for item in all_items])
    ubicaciones_json = json.dumps([
        {'pk': u.pk, 'nombre': u.nombre, 'tipo': u.get_tipo_display()}
        for u in ubicaciones
    ])

    if request.method == 'POST':
        form = ConteoForm(request.POST)

        item_ids = request.POST.getlist('item[]')
        ubicacion_ids = request.POST.getlist('ubicacion[]')
        cantidades = request.POST.getlist('cantidad_contada[]')

        # Lista ordenada: [{item_id, ub_id, cant}] para todos los ítems con cantidad
        filas_previas = [
            {'item_id': iid, 'ub_id': uid, 'cant': cant}
            for iid, uid, cant in zip(item_ids, ubicacion_ids, cantidades)
            if cant.strip()
        ]
        filas_previas_json = json.dumps(filas_previas)
        tipo_conteo_previo = request.POST.get('tipo_conteo', 'camiseta')

        def _render_error(f):
            return render(request, 'conteos/form.html', {
                'form': f,
                'items_por_tipo_json': items_por_tipo_json,
                'all_items_json': all_items_json,
                'ubicaciones_json': ubicaciones_json,
                'hoy': hoy,
                'filas_previas_json': filas_previas_json,
                'tipo_conteo_inicial': tipo_conteo_previo,
                'tipos_conteo_fijos': ['camiseta', 'pigmentos', 'lisa'],
            })

        if not form.is_valid():
            return _render_error(form)

        fecha = form.cleaned_data['fecha']
        turno = form.cleaned_data['turno']
        tipo_conteo = form.cleaned_data['tipo_conteo']

        if Conteo.objects.filter(fecha=fecha, turno=turno, tipo_conteo=tipo_conteo, anulado=False).exists():
            label_tipo = dict(Conteo.TIPO_CONTEO_CHOICES).get(tipo_conteo, tipo_conteo)
            label_turno = dict(Conteo.TURNO_CHOICES).get(turno, turno)
            messages.error(
                request,
                f'Ya existe un conteo de {label_tipo} - {label_turno} para {fecha}.'
            )
            return _render_error(form)

        errores = []
        filas = []

        for i, (item_id, ub_id, cant_str) in enumerate(
            zip(item_ids, ubicacion_ids, cantidades), 1
        ):
            cant_str = cant_str.strip()
            if not cant_str:
                continue
            if not item_id:
                errores.append(f'Fila {i}: ítem inválido.')
                continue
            if not ub_id:
                errores.append(f'Fila {i}: selecciona una ubicación.')
                continue
            try:
                cantidad_contada = Decimal(cant_str)
            except Exception:
                errores.append(f'Fila {i}: cantidad inválida.')
                continue
            if cantidad_contada < 0:
                errores.append(f'Fila {i}: la cantidad no puede ser negativa.')
                continue
            try:
                item = Item.objects.get(pk=item_id, activo=True)
            except Item.DoesNotExist:
                errores.append(f'Fila {i}: ítem no encontrado.')
                continue
            try:
                ubicacion = Ubicacion.objects.get(pk=ub_id)
            except Ubicacion.DoesNotExist:
                errores.append(f'Fila {i}: ubicación no encontrada.')
                continue

            cantidad_sistema = stocks_map.get((item.pk, ubicacion.pk), Decimal('0'))
            filas.append((item, ubicacion, cantidad_contada, cantidad_sistema))

        if errores:
            for e in errores:
                messages.error(request, e)
            return _render_error(form)

        if not filas:
            messages.error(request, 'Ingresá al menos una cantidad en el conteo.')
            return _render_error(form)

        with transaction.atomic():
            conteo = form.save(commit=False)
            conteo.usuario = request.user
            conteo.save()
            for item, ubicacion, cantidad_contada, cantidad_sistema in filas:
                ConteoDetalle.objects.create(
                    conteo=conteo,
                    item=item,
                    ubicacion=ubicacion,
                    cantidad_contada=cantidad_contada,
                    cantidad_sistema_al_conteo=cantidad_sistema,
                )

        label_tipo = dict(Conteo.TIPO_CONTEO_CHOICES).get(conteo.tipo_conteo, conteo.tipo_conteo)
        messages.success(
            request,
            f'Conteo {label_tipo} - {conteo.get_turno_display()} registrado con {len(filas)} ítem(s). '
            f'Revisá la conciliación para calcular diferencias.'
        )
        return redirect('conteo_conciliar', pk=conteo.pk)

    form = ConteoForm(initial={
        'fecha': hoy,
        'tipo_conteo': 'camiseta',
        'fecha_hora_conteo': timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M'),
    })
    return render(request, 'conteos/form.html', {
        'form': form,
        'items_por_tipo_json': items_por_tipo_json,
        'all_items_json': all_items_json,
        'ubicaciones_json': ubicaciones_json,
        'hoy': hoy,
        'filas_previas_json': '[]',
        'tipo_conteo_inicial': 'camiseta',
        'tipos_conteo_fijos': ['camiseta', 'pigmentos', 'lisa'],
    })


@login_required
@permission_required(_perm('registrar_conteo'), raise_exception=True)
def conteo_detalle(request, pk):
    conteo = get_object_or_404(Conteo, pk=pk)
    detalles = conteo.detalles.select_related('item', 'ubicacion').order_by('item__orden', 'item__nombre')
    total_contado = detalles.aggregate(t=Sum('cantidad_contada'))['t'] or 0
    total_dif_original = detalles.aggregate(t=Sum('diferencia_original'))['t'] or 0

    context = {
        'conteo': conteo,
        'detalles': detalles,
        'total_contado': total_contado,
        'total_dif_original': total_dif_original,
    }
    return render(request, 'conteos/detalle.html', context)


@login_required
@permission_required(_perm('aplicar_conciliacion'), raise_exception=True)
def conteo_conciliar(request, pk):
    conteo = get_object_or_404(Conteo, pk=pk)
    if conteo.anulado:
        messages.error(request, 'Este conteo está anulado y no puede conciliarse.')
        return redirect('conteo_detalle', pk=pk)
    detalles = conteo.detalles.select_related('item', 'ubicacion').order_by('item__orden', 'item__nombre')

    plan = []
    with transaction.atomic():
        for detalle in detalles:
            # Stock teórico al momento del conteo usando fecha_movimiento como
            # timestamp oficial. No depende de cuándo se registró el movimiento.
            stock_teorico = _stock_en_momento(
                detalle.item, detalle.ubicacion, conteo.fecha_hora_conteo
            )
            diferencia_final = detalle.cantidad_contada - stock_teorico

            # Persistir diferencia_final si cambió
            if detalle.diferencia_final != diferencia_final:
                detalle.diferencia_final = diferencia_final
                ConteoDetalle.objects.filter(pk=detalle.pk).update(
                    diferencia_final=diferencia_final
                )

            # Movimientos registrados DESPUÉS del conteo pero con fecha_movimiento
            # ANTES del conteo. Se muestran para transparencia: ya están
            # correctamente incluidos en stock_teorico (no son "atrasados" — son
            # movimientos reales anteriores al conteo, solo ingresados tarde).
            movs_tardios = (
                DetalleMovimiento.objects
                .filter(
                    item=detalle.item,
                    movimiento__anulado=False,
                    movimiento__eliminado=False,
                    movimiento__fecha__gt=conteo.fecha_hora_conteo,
                    movimiento__fecha_movimiento__lte=conteo.fecha_hora_conteo,
                )
                .filter(
                    Q(ubicacion_destino=detalle.ubicacion)
                    | Q(ubicacion_origen=detalle.ubicacion)
                )
                .select_related(
                    'movimiento', 'movimiento__usuario',
                    'ubicacion_origen', 'ubicacion_destino',
                )
                .order_by('movimiento__fecha_movimiento')
            )

            plan.append({
                'detalle': detalle,
                'stock_teorico': stock_teorico,
                'diferencia_final': diferencia_final,
                'movs_tardios': movs_tardios,   # solo informativos
            })

    return render(request, 'conteos/conciliar.html', {
        'conteo': conteo,
        'plan': plan,
    })


@login_required
@permission_required(_perm('aplicar_conciliacion'), raise_exception=True)
def conteo_ajustar_detalle(request, pk, det_pk):
    if request.method != 'POST':
        return redirect('conteo_conciliar', pk=pk)

    conteo = get_object_or_404(Conteo, pk=pk)
    if conteo.anulado:
        messages.error(request, 'Este conteo está anulado.')
        return redirect('conteo_detalle', pk=pk)
    detalle = get_object_or_404(ConteoDetalle, pk=det_pk, conteo=conteo)

    if detalle.ajuste_aplicado:
        messages.warning(request, 'Este ajuste ya fue aplicado.')
        return redirect('conteo_conciliar', pk=pk)

    if detalle.diferencia_final is None:
        messages.error(request, 'Primero calculá la diferencia final en la pantalla de conciliación.')
        return redirect('conteo_conciliar', pk=pk)

    if detalle.diferencia_final == 0:
        messages.info(request, f'{detalle.item.nombre}: no hay diferencia que ajustar.')
        return redirect('conteo_conciliar', pk=pk)

    with transaction.atomic():
        mov_ajuste = MovimientoInventario.objects.create(
            tipo_movimiento='ajuste',
            motivo=f'Ajuste por conciliación — Conteo #{conteo.pk} ({conteo.get_turno_display()} {conteo.fecha})',
            usuario=request.user,
        )
        det_ajuste = DetalleMovimiento.objects.create(
            movimiento=mov_ajuste,
            item=detalle.item,
            cantidad=detalle.diferencia_final,
            ubicacion_destino=detalle.ubicacion,
        )
        _aplicar_efecto_detalle(det_ajuste)
        _cerrar_pendientes_conciliacion(detalle.item, detalle.ubicacion)
        ConteoDetalle.objects.filter(pk=detalle.pk).update(ajuste_aplicado=True)
        conteo.refresh_from_db()
        conteo.actualizar_estado()

    send_event('count_difference', {
        'conteo_id': conteo.pk, 'item': detalle.item.nombre, 'codigo': detalle.item.codigo,
        'diferencia': str(detalle.diferencia_final), 'ubicacion': detalle.ubicacion.nombre,
        'usuario': request.user.username,
    })
    notify_stock(detalle.item, movimiento='ajuste', usuario=request.user.username)
    messages.success(request, f'Ajuste aplicado: {detalle.item.nombre} ({detalle.diferencia_final:+g} {detalle.item.unidad_medida}).')
    return redirect('conteo_conciliar', pk=pk)


@login_required
@permission_required(_perm('aplicar_conciliacion'), raise_exception=True)
def conteo_ajustar_todos(request, pk):
    if request.method != 'POST':
        return redirect('conteo_conciliar', pk=pk)

    conteo = get_object_or_404(Conteo, pk=pk)
    if conteo.anulado:
        messages.error(request, 'Este conteo está anulado.')
        return redirect('conteo_detalle', pk=pk)
    detalles = conteo.detalles.filter(
        ajuste_aplicado=False,
        diferencia_final__isnull=False,
    ).exclude(diferencia_final=0).select_related('item', 'ubicacion')

    if not detalles.exists():
        messages.info(request, 'No hay ajustes pendientes con diferencia.')
        return redirect('conteo_conciliar', pk=pk)

    count = 0
    with transaction.atomic():
        for detalle in detalles:
            mov_ajuste = MovimientoInventario.objects.create(
                tipo_movimiento='ajuste',
                motivo=f'Ajuste por conciliación — Conteo #{conteo.pk} ({conteo.get_turno_display()} {conteo.fecha})',
                usuario=request.user,
            )
            det_ajuste = DetalleMovimiento.objects.create(
                movimiento=mov_ajuste,
                item=detalle.item,
                cantidad=detalle.diferencia_final,
                ubicacion_destino=detalle.ubicacion,
            )
            _aplicar_efecto_detalle(det_ajuste)
            _cerrar_pendientes_conciliacion(detalle.item, detalle.ubicacion)
            count += 1
        ConteoDetalle.objects.filter(
            conteo=conteo, ajuste_aplicado=False,
            diferencia_final__isnull=False
        ).exclude(diferencia_final=0).update(ajuste_aplicado=True)
        conteo.refresh_from_db()
        conteo.actualizar_estado()

    send_event('count_difference', {
        'conteo_id': conteo.pk, 'ajustes_aplicados': count,
        'usuario': request.user.username,
    })
    messages.success(request, f'{count} ajuste(s) aplicado(s) exitosamente.')
    return redirect('conteo_conciliar', pk=pk)


@login_required
@permission_required(_perm('aplicar_conciliacion'), raise_exception=True)
def conteo_marcar_conciliado(request, pk):
    if request.method != 'POST':
        return redirect('conteo_conciliar', pk=pk)

    conteo = get_object_or_404(Conteo, pk=pk)
    if conteo.anulado:
        messages.error(request, 'Este conteo está anulado.')
        return redirect('conteo_detalle', pk=pk)

    # Verificar que no queden diferencias sin ajustar
    pendientes = conteo.detalles.filter(
        ajuste_aplicado=False,
        diferencia_final__isnull=False,
    ).exclude(diferencia_final=0).count()

    sin_calcular = conteo.detalles.filter(diferencia_final__isnull=True).count()

    if sin_calcular > 0:
        messages.warning(request, f'Hay {sin_calcular} línea(s) sin diferencia calculada. Abrí la conciliación primero.')
        return redirect('conteo_conciliar', pk=pk)

    if pendientes > 0:
        messages.warning(request, f'Hay {pendientes} ajuste(s) pendiente(s) con diferencia. Aplicalos o ignoralos antes de cerrar.')
        return redirect('conteo_conciliar', pk=pk)

    conteo.estado = 'conciliado'
    conteo.save(update_fields=['estado'])
    messages.success(request, 'Conteo marcado como conciliado.')
    return redirect('conteo_detalle', pk=pk)


# ─── MÁQUINAS ─────────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def maquina_lista(request):
    maquinas = Maquina.objects.order_by('nombre')
    return render(request, 'maquinas/lista.html', {'maquinas': maquinas})


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def maquina_crear(request):
    if request.method == 'POST':
        form = MaquinaForm(request.POST)
        if form.is_valid():
            m = form.save()
            messages.success(request, f'Máquina "{m.nombre}" creada.')
            return redirect('maquina_lista')
    else:
        form = MaquinaForm()
    return render(request, 'maquinas/form.html', {'form': form, 'titulo': 'Nueva Máquina'})


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def maquina_editar(request, pk):
    maquina = get_object_or_404(Maquina, pk=pk)
    if request.method == 'POST':
        form = MaquinaForm(request.POST, instance=maquina)
        if form.is_valid():
            form.save()
            messages.success(request, f'Máquina "{maquina.nombre}" actualizada.')
            return redirect('maquina_lista')
    else:
        form = MaquinaForm(instance=maquina)
    return render(request, 'maquinas/form.html', {
        'form': form, 'titulo': f'Editar: {maquina.nombre}', 'maquina': maquina
    })


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def maquina_toggle_activo(request, pk):
    maquina = get_object_or_404(Maquina, pk=pk)
    maquina.activo = not maquina.activo
    maquina.save()
    messages.success(request, f'Máquina "{maquina.nombre}" {"activada" if maquina.activo else "desactivada"}.')
    return redirect('maquina_lista')


# ─── CLIENTES ─────────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def cliente_lista(request):
    q = request.GET.get('q', '')
    clientes = Cliente.objects.order_by('nombre')
    if q:
        clientes = clientes.filter(Q(nombre__icontains=q) | Q(rtn__icontains=q))
    return render(request, 'clientes/lista.html', {'clientes': clientes, 'q': q})


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def cliente_crear(request):
    if request.method == 'POST':
        form = ClienteForm(request.POST)
        if form.is_valid():
            c = form.save()
            messages.success(request, f'Cliente "{c.nombre}" creado.')
            return redirect('cliente_lista')
    else:
        form = ClienteForm()
    return render(request, 'clientes/form.html', {'form': form, 'titulo': 'Nuevo Cliente'})


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def cliente_editar(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    if request.method == 'POST':
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            messages.success(request, f'Cliente "{cliente.nombre}" actualizado.')
            return redirect('cliente_lista')
    else:
        form = ClienteForm(instance=cliente)
    return render(request, 'clientes/form.html', {
        'form': form, 'titulo': f'Editar: {cliente.nombre}', 'cliente': cliente
    })


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def cliente_toggle_activo(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    cliente.activo = not cliente.activo
    cliente.save()
    messages.success(request, f'Cliente "{cliente.nombre}" {"activado" if cliente.activo else "desactivado"}.')
    return redirect('cliente_lista')


# ─── REPORTES ─────────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('ver_reportes'), raise_exception=True)
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
def reporte_produccion_avanzado(request):
    """
    Reporte de producción + salidas de PT para un rango de fechas.
    Agrupa por día / semana / mes y muestra desglose por producto.
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
    # Máximo 365 días
    if (fecha_fin - fecha_inicio).days > 364:
        fecha_inicio = fecha_fin - timedelta(days=364)

    agrupar_por = request.GET.get('agrupar_por', 'dia')
    if agrupar_por not in ('dia', 'semana', 'mes'):
        agrupar_por = 'dia'

    export = request.GET.get('export', '')

    # ── Producción batch ────────────────────────────────────────────────────────
    prod_rango = _calcular_produccion_rango(fecha_inicio, fecha_fin)

    # ── Salidas de PT por fecha_movimiento.date() ────────────────────────────────
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

    sal_x_fecha: dict = {}    # date → total
    sal_x_item:  dict = {}    # item_pk → {'item': obj, 'total': qty}
    for det in salidas_qs:
        fd = det.movimiento.fecha_movimiento.date()
        sal_x_fecha[fd] = sal_x_fecha.get(fd, Decimal('0')) + det.cantidad
        pk = det.item_id
        if pk not in sal_x_item:
            sal_x_item[pk] = {'item': det.item, 'total': Decimal('0')}
        sal_x_item[pk]['total'] += det.cantidad

    # ── Datos diarios ───────────────────────────────────────────────────────────
    dias_data = []
    cur = fecha_inicio
    while cur <= fecha_fin:
        p        = prod_rango.get(cur, {})
        pd       = p.get('prod_dia',   Decimal('0'))
        pn       = p.get('prod_noche', Decimal('0'))
        pt       = pd + pn
        sal      = sal_x_fecha.get(cur, Decimal('0'))
        dias_data.append({
            'fecha':      cur,
            'prod_dia':   pd,
            'prod_noche': pn,
            'prod_total': pt,
            'salidas':    sal,
            'diferencia': pt - sal,
            'tiene_dia':  p.get('tiene_dia',   False),
            'tiene_noche': p.get('tiene_noche', False),
            'por_item':   p.get('por_item',     {}),
        })
        cur += timedelta(days=1)

    # ── Agrupación ──────────────────────────────────────────────────────────────
    def _gkey(d):
        f = d['fecha']
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
    for d in dias_data:
        k = _gkey(d)
        if k != cur_key:
            if cur_g:
                cur_g['diferencia'] = cur_g['prod_total'] - cur_g['salidas']
                grupos.append(cur_g)
            cur_key = k
            cur_g = {
                'key': k, 'label': _glabel(k),
                'prod_dia': Decimal('0'), 'prod_noche': Decimal('0'),
                'prod_total': Decimal('0'), 'salidas': Decimal('0'),
                'diferencia': Decimal('0'),
                'num_dias': 0, 'dias_con_dato': 0,
                'fechas': [],
            }
        cur_g['prod_dia']   += d['prod_dia']
        cur_g['prod_noche'] += d['prod_noche']
        cur_g['prod_total'] += d['prod_total']
        cur_g['salidas']    += d['salidas']
        cur_g['num_dias']   += 1
        if d['tiene_dia'] or d['tiene_noche']:
            cur_g['dias_con_dato'] += 1
        cur_g['fechas'].append(d)
    if cur_g:
        cur_g['diferencia'] = cur_g['prod_total'] - cur_g['salidas']
        grupos.append(cur_g)

    # ── Totales generales ───────────────────────────────────────────────────────
    total_prod_dia   = sum(d['prod_dia']   for d in dias_data)
    total_prod_noche = sum(d['prod_noche'] for d in dias_data)
    total_prod       = total_prod_dia + total_prod_noche
    total_salidas    = sum(d['salidas']    for d in dias_data)
    total_diferencia = total_prod - total_salidas
    num_dias_rango   = (fecha_fin - fecha_inicio).days + 1
    dias_con_dato    = sum(1 for d in dias_data if d['tiene_dia'] or d['tiene_noche'])

    # ── Por producto ────────────────────────────────────────────────────────────
    all_pks = set(sal_x_item.keys())
    for d in dias_data:
        all_pks.update(d['por_item'].keys())

    items_pt = (
        Item.objects
        .filter(pk__in=all_pks, tipo='producto', activo=True)
        .order_by('orden', 'nombre')
    )
    por_producto = []
    for item in items_pt:
        prod_item = sum(
            d['por_item'].get(item.pk, {}).get('dia',   Decimal('0'))
            + d['por_item'].get(item.pk, {}).get('noche', Decimal('0'))
            for d in dias_data
        )
        sal_item = sal_x_item.get(item.pk, {}).get('total', Decimal('0'))
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
        w.writerow(['Período', 'Prod. día', 'Prod. noche', 'Prod. total', 'Salidas', 'Diferencia'])
        for g in grupos:
            w.writerow([g['label'], g['prod_dia'], g['prod_noche'],
                        g['prod_total'], g['salidas'], g['diferencia']])
        w.writerow([])
        w.writerow(['Producto', 'Producción total', 'Salidas', 'Diferencia'])
        for p in por_producto:
            w.writerow([p['item'].nombre, p['prod_total'], p['salidas'], p['diferencia']])
        return resp

    return render(request, 'reportes/produccion_avanzado.html', {
        'fecha_inicio':      fecha_inicio,
        'fecha_fin':         fecha_fin,
        'agrupar_por':       agrupar_por,
        'grupos':            grupos,
        'por_producto':      por_producto,
        'total_prod_dia':    total_prod_dia,
        'total_prod_noche':  total_prod_noche,
        'total_prod':        total_prod,
        'total_salidas':     total_salidas,
        'total_diferencia':  total_diferencia,
        'num_dias_rango':    num_dias_rango,
        'dias_con_dato':     dias_con_dato,
    })


# ─── API ──────────────────────────────────────────────────────────────────────

@login_required
def api_categoria_nueva(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body)
        nombre = data.get('nombre', '').strip()
        if not nombre:
            return JsonResponse({'error': 'Nombre requerido'}, status=400)
        cat, created = Categoria.objects.get_or_create(nombre=nombre)
        return JsonResponse({'id': cat.pk, 'nombre': cat.nombre, 'created': created})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def api_item_info(request, pk):
    item = get_object_or_404(Item, pk=pk)
    stocks = list(Stock.objects.filter(item=item).values('ubicacion__id', 'ubicacion__nombre', 'cantidad_actual'))
    return JsonResponse({
        'tipo': item.tipo,
        'unidad_medida': item.unidad_medida,
        'stock_total': str(item.stock_total()),
        'stocks': [
            {'ubicacion_id': s['ubicacion__id'], 'ubicacion': s['ubicacion__nombre'],
             'cantidad': str(s['cantidad_actual'])}
            for s in stocks
        ]
    })


# ─── PRODUCCIÓN ───────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('registrar_produccion'), raise_exception=True)
def produccion_nueva(request):
    ubicaciones = Ubicacion.objects.all()

    if request.method == 'POST':
        form = ProduccionForm(request.POST)
        if form.is_valid():
            item = form.cleaned_data['item']
            cantidad = form.cleaned_data['cantidad']
            ubicacion = form.cleaned_data['ubicacion_destino']
            fecha_movimiento = form.cleaned_data['fecha_movimiento']
            motivo = form.cleaned_data.get('motivo', '') or f'Producción registrada'

            if timezone.is_naive(fecha_movimiento):
                fecha_movimiento = timezone.make_aware(fecha_movimiento)

            with transaction.atomic():
                mov_prod = MovimientoInventario.objects.create(
                    tipo_movimiento='entrada',
                    motivo=motivo,
                    fecha_movimiento=fecha_movimiento,
                    usuario=request.user,
                )
                det_prod = DetalleMovimiento.objects.create(
                    movimiento=mov_prod,
                    item=item,
                    cantidad=cantidad,
                    ubicacion_destino=ubicacion,
                )
                _aplicar_efecto_detalle(det_prod)

            send_event('production_created', {
                'item': item.nombre, 'codigo': item.codigo,
                'cantidad': str(cantidad), 'ubicacion': ubicacion.nombre,
                'usuario': request.user.username,
                'fecha_movimiento': fecha_movimiento.isoformat(),
            })
            notify_stock(item, movimiento='produccion', usuario=request.user.username)

            messages.success(request, f'Producción registrada: {cantidad} {item.unidad_medida} de {item.nombre}.')
            return redirect('produccion_nueva')
    else:
        form = ProduccionForm(initial={
            'fecha_movimiento': timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M'),
        })

    return render(request, 'produccion/form.html', {
        'form': form,
        'ubicaciones': ubicaciones,
    })


# ─── IMPORTAR EXCEL ───────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('importar_excel'), raise_exception=True)
def importar_items(request):
    resultados = None

    if request.method == 'POST':
        form = ImportarItemsForm(request.POST, request.FILES)
        if form.is_valid():
            archivo = request.FILES['archivo']
            resultados = _procesar_excel_items(archivo)
    else:
        form = ImportarItemsForm()

    return render(request, 'importar/form.html', {
        'form': form,
        'resultados': resultados,
    })


def _procesar_excel_items(archivo):
    try:
        import openpyxl
    except ImportError:
        return {'error': 'openpyxl no está instalado.', 'creados': 0, 'actualizados': 0, 'errores': []}

    creados = 0
    actualizados = 0
    errores = []

    try:
        wb = openpyxl.load_workbook(archivo, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    except Exception as e:
        return {'error': f'No se pudo leer el archivo: {e}', 'creados': 0, 'actualizados': 0, 'errores': []}

    if not rows:
        return {'error': 'El archivo está vacío.', 'creados': 0, 'actualizados': 0, 'errores': []}

    # First row must be headers; find column indices
    headers = [str(h).strip().lower() if h else '' for h in rows[0]]
    col = {name: headers.index(name) for name in ('codigo', 'nombre', 'tipo', 'unidad_medida') if name in headers}

    required = ['codigo', 'nombre', 'tipo', 'unidad_medida']
    missing = [r for r in required if r not in col]
    if missing:
        return {
            'error': f'Columnas requeridas faltantes: {", ".join(missing)}.',
            'creados': 0, 'actualizados': 0, 'errores': [],
        }

    col_opt = lambda name: headers.index(name) if name in headers else None
    idx_desc = col_opt('descripcion')
    idx_cat = col_opt('categoria')
    idx_min = col_opt('stock_minimo')

    TIPOS_VALIDOS = {'producto', 'repuesto', 'consumible'}

    for row_num, row in enumerate(rows[1:], start=2):
        try:
            codigo = str(row[col['codigo']] or '').strip()
            nombre = str(row[col['nombre']] or '').strip()
            tipo = str(row[col['tipo']] or '').strip().lower()
            unidad = str(row[col['unidad_medida']] or '').strip()

            if not codigo or not nombre:
                errores.append(f'Fila {row_num}: código o nombre vacío, se omite.')
                continue
            if tipo not in TIPOS_VALIDOS:
                errores.append(f'Fila {row_num} ({codigo}): tipo "{tipo}" inválido (usar: producto/repuesto/consumible).')
                continue
            if not unidad:
                errores.append(f'Fila {row_num} ({codigo}): unidad de medida requerida.')
                continue

            descripcion = str(row[idx_desc] or '').strip() if idx_desc is not None else ''

            categoria = None
            if idx_cat is not None and row[idx_cat]:
                cat_nombre = str(row[idx_cat]).strip()
                if cat_nombre:
                    categoria, _ = Categoria.objects.get_or_create(nombre=cat_nombre)

            stock_minimo = Decimal('0')
            if idx_min is not None and row[idx_min] is not None:
                try:
                    stock_minimo = Decimal(str(row[idx_min]))
                except Exception:
                    pass

            item, created = Item.objects.update_or_create(
                codigo=codigo,
                defaults={
                    'nombre': nombre,
                    'tipo': tipo,
                    'unidad_medida': unidad,
                    'descripcion': descripcion,
                    'categoria': categoria,
                    'stock_minimo': stock_minimo,
                    'activo': True,
                },
            )
            if created:
                creados += 1
            else:
                actualizados += 1

        except Exception as e:
            errores.append(f'Fila {row_num}: error inesperado — {e}')

    return {'creados': creados, 'actualizados': actualizados, 'errores': errores, 'error': None}


@login_required
@permission_required(_perm('importar_excel'), raise_exception=True)
def descargar_plantilla(request):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        messages.error(request, 'openpyxl no está instalado.')
        return redirect('importar_items')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Items'

    headers = ['codigo', 'nombre', 'tipo', 'unidad_medida', 'stock_minimo', 'categoria', 'descripcion']
    header_fill = PatternFill('solid', fgColor='003087')
    header_font = Font(bold=True, color='FFFFFF')

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    # Example rows
    ejemplos = [
        ['BOLSA-001', 'Bolsa de polietileno 10x15', 'producto', 'unidad', 100, 'Bolsas', ''],
        ['REP-001', 'Rodamiento 6205', 'repuesto', 'pieza', 5, 'Repuestos', 'Para máquina selladora'],
        ['CONS-001', 'Cinta adhesiva', 'consumible', 'rollo', 10, 'Consumibles', ''],
    ]
    for row_data in ejemplos:
        ws.append(row_data)

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = max(12, max_len + 4)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="plantilla_items.xlsx"'
    return response


# ─── USUARIOS ─────────────────────────────────────────────────────────────────

def _staff_required(view_func):
    """Restrict view to staff/superusers only; log denied attempts."""
    from functools import wraps
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        if not (request.user.is_staff or request.user.is_superuser):
            ip = _get_client_ip(request)
            send_security_event(
                'forbidden_403',
                title    = '🚫 Acceso denegado a ruta administrativa',
                user     = request.user.username,
                ip       = ip,
                path     = request.path,
                user_agent = request.META.get('HTTP_USER_AGENT', '')[:200],
                message  = f'Usuario "{request.user.username}" sin permisos de staff intentó acceder a {request.path}',
            )
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped


def _get_grupo(user):
    return user.groups.first().name if user.groups.exists() else ''


@login_required
@_staff_required
def usuario_lista(request):
    usuarios = (
        User.objects.prefetch_related('groups')
        .order_by('username')
    )
    data = [
        {'user': u, 'grupo': _get_grupo(u)}
        for u in usuarios
    ]
    return render(request, 'usuarios/lista.html', {'data': data})


@login_required
@_staff_required
def usuario_crear(request):
    if request.method == 'POST':
        form = UsuarioCrearForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            user = User.objects.create_user(
                username=cd['username'],
                password=cd['password'],
                first_name=cd.get('first_name', ''),
                last_name=cd.get('last_name', ''),
                email=cd.get('email', ''),
            )
            grupo_nombre = cd.get('grupo')
            if grupo_nombre:
                try:
                    grupo = Group.objects.get(name=grupo_nombre)
                    user.groups.set([grupo])
                except Group.DoesNotExist:
                    pass
            messages.success(request, f'Usuario "{user.username}" creado exitosamente.')
            return redirect('usuario_lista')
    else:
        form = UsuarioCrearForm()

    return render(request, 'usuarios/form.html', {'form': form, 'titulo': 'Nuevo Usuario'})


@login_required
@_staff_required
def usuario_editar(request, pk):
    usuario = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        form = UsuarioEditarForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            usuario.first_name = cd.get('first_name', '')
            usuario.last_name = cd.get('last_name', '')
            usuario.email = cd.get('email', '')
            usuario.is_active = cd.get('is_active', True)

            nueva_pass = cd.get('nueva_password')
            if nueva_pass:
                usuario.set_password(nueva_pass)

            usuario.save()

            grupo_nombre = cd.get('grupo')
            if grupo_nombre:
                try:
                    grupo = Group.objects.get(name=grupo_nombre)
                    usuario.groups.set([grupo])
                except Group.DoesNotExist:
                    usuario.groups.clear()
            else:
                usuario.groups.clear()

            messages.success(request, f'Usuario "{usuario.username}" actualizado.')
            return redirect('usuario_lista')
    else:
        form = UsuarioEditarForm(initial={
            'first_name': usuario.first_name,
            'last_name': usuario.last_name,
            'email': usuario.email,
            'is_active': usuario.is_active,
            'grupo': _get_grupo(usuario),
        })

    return render(request, 'usuarios/form.html', {
        'form': form,
        'titulo': f'Editar: {usuario.username}',
        'usuario': usuario,
    })


# ─── REPORTE CONSUMO PIGMENTOS ────────────────────────────────────────────────

@login_required
@permission_required(_perm('ver_reportes'), raise_exception=True)
def reporte_consumo_pigmentos(request):
    """
    Reporte de consumo de pigmentos en un rango de fechas.

    Consumo = ajustes negativos sobre ítems de categoría Pigmentos.
    Muestra: consumo total, promedio diario, stock actual, días de cobertura,
    estado (ok / bajo / crítico) y pedido sugerido.
    """
    hoy = date.today()

    # ── Filtros ───────────────────────────────────────────────────────────────
    def _parse_date(s, fallback):
        try:
            return date.fromisoformat(s) if s else fallback
        except ValueError:
            return fallback

    fecha_inicio = _parse_date(request.GET.get('fecha_inicio', ''), hoy - timedelta(days=30))
    fecha_fin    = _parse_date(request.GET.get('fecha_fin', ''),    hoy)
    if fecha_fin < fecha_inicio:
        fecha_fin = fecha_inicio

    pigmento_pk  = request.GET.get('pigmento', '').strip()
    try:
        dias_objetivo = max(1, int(request.GET.get('dias_objetivo', 14)))
    except (ValueError, TypeError):
        dias_objetivo = 14

    dias_rango = max(1, (fecha_fin - fecha_inicio).days + 1)

    # ── Pigmentos activos ─────────────────────────────────────────────────────
    pigmentos_qs = (
        Item.objects
        .filter(activo=True, tipo='consumible', categoria__nombre__iexact='Pigmentos')
        .select_related('categoria')
        .annotate(stock_calc=_STOCK_ANN)
        .order_by('orden', 'nombre')
    )
    if pigmento_pk:
        pigmentos_qs = pigmentos_qs.filter(pk=pigmento_pk)

    todos_pigmentos = (
        Item.objects
        .filter(activo=True, tipo='consumible', categoria__nombre__iexact='Pigmentos')
        .order_by('orden', 'nombre')
    )

    # ── Consumo por ítem: ajustes negativos en el rango ───────────────────────
    consumos_base = DetalleMovimiento.objects.filter(
        movimiento__tipo_movimiento='ajuste',
        movimiento__anulado=False,
        movimiento__eliminado=False,
        movimiento__fecha_movimiento__date__gte=fecha_inicio,
        movimiento__fecha_movimiento__date__lte=fecha_fin,
        item__tipo='consumible',
        item__categoria__nombre__iexact='Pigmentos',
        cantidad__lt=0,
    )
    if pigmento_pk:
        consumos_base = consumos_base.filter(item_id=pigmento_pk)

    consumo_por_item = {
        row['item_id']: abs(row['total'])
        for row in consumos_base.values('item_id').annotate(total=Sum('cantidad'))
    }

    # ── Construir tabla de resultados ─────────────────────────────────────────
    ESTADO_LABELS = {
        'ok':          'OK',
        'bajo':        'Bajo',
        'critico':     'Crítico',
        'sin_consumo': 'Sin consumo',
    }

    resultados = []
    total_consumo  = Decimal('0')
    total_criticos = 0
    total_pedido   = Decimal('0')

    for pig in pigmentos_qs:
        consumo = consumo_por_item.get(pig.pk, Decimal('0'))
        stock   = pig.stock_calc or Decimal('0')

        if consumo > 0:
            promedio_diario = consumo / Decimal(str(dias_rango))
            dias_cob = float(stock / promedio_diario) if promedio_diario else None
            pedido   = max(Decimal('0'), promedio_diario * Decimal(str(dias_objetivo)) - stock)
        else:
            promedio_diario = Decimal('0')
            dias_cob = None
            pedido   = Decimal('0')

        if dias_cob is None:
            estado = 'sin_consumo'
        elif dias_cob < 3:
            estado = 'critico'
            total_criticos += 1
        elif dias_cob <= 7:
            estado = 'bajo'
        else:
            estado = 'ok'

        total_consumo += consumo
        total_pedido  += pedido

        resultados.append({
            'item':           pig,
            'consumo':        consumo,
            'promedio_diario': round(promedio_diario, 2),
            'stock':          stock,
            'dias_cobertura': round(dias_cob, 1) if dias_cob is not None else None,
            'pedido':         round(pedido, 2),
            'estado':         estado,
            'estado_label':   ESTADO_LABELS[estado],
        })

    # ── Detalle de movimientos (solo cuando se filtra un pigmento) ─────────────
    detalle_movimientos = []
    if pigmento_pk:
        detalle_movimientos = list(
            consumos_base
            .select_related('movimiento', 'movimiento__usuario', 'item')
            .order_by('-movimiento__fecha_movimiento')
        )

    # ── Exportar CSV ──────────────────────────────────────────────────────────
    if request.GET.get('export') == 'csv':
        fname = f'consumo_pigmentos_{fecha_inicio}_{fecha_fin}.csv'
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{fname}"'
        response.write('﻿')  # BOM para Excel
        writer = csv.writer(response)
        writer.writerow([
            'Pigmento', 'Código', 'Consumo total', 'Promedio diario',
            'Stock actual', 'Cobertura (días)', 'Pedido sugerido', 'Unidad', 'Estado',
        ])
        for r in resultados:
            writer.writerow([
                r['item'].nombre, r['item'].codigo,
                r['consumo'], r['promedio_diario'],
                r['stock'],
                r['dias_cobertura'] if r['dias_cobertura'] is not None else '',
                r['pedido'], r['item'].unidad_medida,
                r['estado_label'],
            ])
        return response

    return render(request, 'reportes/pigmentos.html', {
        'resultados':          resultados,
        'todos_pigmentos':     todos_pigmentos,
        'fecha_inicio':        fecha_inicio,
        'fecha_fin':           fecha_fin,
        'dias_rango':          dias_rango,
        'dias_objetivo':       dias_objetivo,
        'pigmento_pk':         pigmento_pk,
        'total_consumo':       total_consumo,
        'total_criticos':      total_criticos,
        'total_pedido':        total_pedido,
        'detalle_movimientos': detalle_movimientos,
    })
