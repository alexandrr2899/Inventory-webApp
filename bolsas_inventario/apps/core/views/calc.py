"""
calc.py — Cálculos de producción compartidos por dashboard y reportes.

Funciones puras (sin request): producción día/noche, por rango y por tramos
entre conteos consecutivos tipo Camiseta. Usan modelos vía `from .common import *`.
"""

from .common import *  # noqa: F401,F403


def _calcular_produccion(fecha, salidas_parciales_hasta=None):
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
        if not t_inicio or not t_fin or t_inicio >= t_fin:
            return Decimal('0')
        return (
            DetalleMovimiento.objects
            .filter(
                movimiento__tipo_movimiento='salida',
                movimiento__anulado=False,
                movimiento__eliminado=False,
                movimiento__fecha_movimiento__gte=t_inicio,
                movimiento__fecha_movimiento__lt=t_fin,
            )
            .filter(_filtro_detalle_camiseta())
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
        if conteo_manana and salidas_parciales_hasta:
            salidas_dia = _salidas_entre(
                conteo_manana.fecha_hora_conteo,
                salidas_parciales_hasta,
            )
        else:
            salidas_dia = Decimal('0')
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
        if conteo_tarde and salidas_parciales_hasta:
            salidas_noche = _salidas_entre(
                conteo_tarde.fecha_hora_conteo,
                salidas_parciales_hasta,
            )
        else:
            salidas_noche = Decimal('0')
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


def _calcular_tramos(fecha_inicio, fecha_fin):
    """
    Calcula producción por tramos entre pares de conteos consecutivos
    tipo Camiseta activos.

    Para cada par (c_ini, c_fin) asignado a una fecha dentro de [fecha_inicio, fecha_fin]:

        produccion = total_fin − total_ini + salidas_entre_conteos

    Tipos de tramo
    ──────────────
    'dia'       mañana → tarde  (mismo día)
    'noche'     tarde  → mañana (día siguiente)
    'extendido' cualquier otro (fines de semana, días sin conteo, etc.)

    Devuelve lista de dicts:
        conteo_ini, conteo_fin, tipo, duracion_h,
        produccion, salidas, por_item,
        fecha_asignada (= c_ini.fecha),
        label_rango   (ej. "Sáb 10/05 11:00 → Lun 12/05 08:00")
    """
    # Buscar 3 días antes para capturar el conteo inicial del primer tramo
    fecha_fetch_ini = fecha_inicio - timedelta(days=3)
    fecha_fetch_fin = fecha_fin + timedelta(days=1)

    conteos = list(
        Conteo.objects
        .filter(tipo_conteo='camiseta', anulado=False,
                fecha__range=[fecha_fetch_ini, fecha_fetch_fin])
        .order_by('fecha_hora_conteo')
    )

    if len(conteos) < 2:
        return []

    # ── Batch: ConteoDetalle ────────────────────────────────────────────────────
    conteo_ids = [c.pk for c in conteos]
    detalles_x_conteo: dict = {}
    for cd in (
        ConteoDetalle.objects
        .filter(conteo_id__in=conteo_ids, item__tipo='producto')
        .select_related('item')
    ):
        detalles_x_conteo.setdefault(cd.conteo_id, {})[cd.item_id] = cd.cantidad_contada

    # ── Batch: salidas en el rango temporal de los conteos ─────────────────────
    t_min = conteos[0].fecha_hora_conteo
    t_max = conteos[-1].fecha_hora_conteo
    salidas_list: list = []  # [(fecha_movimiento, item_pk, qty)]
    for det in (
        DetalleMovimiento.objects
        .filter(
            movimiento__tipo_movimiento='salida',
            movimiento__anulado=False,
            movimiento__eliminado=False,
            movimiento__fecha_movimiento__gt=t_min,
            movimiento__fecha_movimiento__lt=t_max,
            item__tipo='producto',
        )
        .select_related('movimiento')
        .only('item_id', 'cantidad', 'movimiento__fecha_movimiento')
    ):
        salidas_list.append((det.movimiento.fecha_movimiento, det.item_id, det.cantidad))

    # ── Auxiliares ──────────────────────────────────────────────────────────────
    def _items(conteo_pk):
        return detalles_x_conteo.get(conteo_pk, {})

    def _salidas_entre(t0, t1):
        r: dict = {}
        for t, pk, qty in salidas_list:
            if t0 < t < t1:
                r[pk] = r.get(pk, Decimal('0')) + qty
        return r

    DIAS_ES = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

    def _fmt_dt(dt):
        dt_local = timezone.localtime(dt)
        return f"{DIAS_ES[dt_local.weekday()]} {dt_local.strftime('%d/%m %H:%M')}"

    def _tipo_tramo(c_ini, c_fin):
        if (c_ini.turno == 'manana' and c_fin.turno == 'tarde'
                and c_ini.fecha == c_fin.fecha):
            return 'dia'
        if (c_ini.turno == 'tarde' and c_fin.turno == 'manana'
                and (c_fin.fecha - c_ini.fecha).days == 1):
            return 'noche'
        return 'extendido'

    # ── Construir tramos ────────────────────────────────────────────────────────
    tramos = []
    for i in range(len(conteos) - 1):
        c_ini = conteos[i]
        c_fin = conteos[i + 1]
        tipo_tramo = _tipo_tramo(c_ini, c_fin)
        fecha_asignada = c_ini.fecha

        # La producción se agrupa por el día operativo donde inicia el tramo:
        # día: mañana → tarde; noche/extendido: tarde o conteo inicial → siguiente cierre.
        if fecha_asignada < fecha_inicio or fecha_asignada > fecha_fin:
            continue

        items_ini = _items(c_ini.pk)
        items_fin = _items(c_fin.pk)
        sal_items = _salidas_entre(c_ini.fecha_hora_conteo, c_fin.fecha_hora_conteo)

        total_ini = sum(items_ini.values(), Decimal('0'))
        total_fin = sum(items_fin.values(), Decimal('0'))
        total_sal = sum(sal_items.values(), Decimal('0'))
        produccion = total_fin - total_ini + total_sal

        por_item: dict = {}
        for pk in set(items_ini) | set(items_fin):
            por_item[pk] = (
                items_fin.get(pk, Decimal('0'))
                - items_ini.get(pk, Decimal('0'))
                + sal_items.get(pk, Decimal('0'))
            )

        duracion_h = round(
            (c_fin.fecha_hora_conteo - c_ini.fecha_hora_conteo).total_seconds() / 3600, 1
        )

        tramos.append({
            'conteo_ini':     c_ini,
            'conteo_fin':     c_fin,
            'tipo':           tipo_tramo,
            'duracion_h':     duracion_h,
            'produccion':     produccion,
            'salidas':        total_sal,
            'diferencia':     produccion - total_sal,
            'por_item':       por_item,
            'fecha_asignada': fecha_asignada,
            'label_rango':    f"{_fmt_dt(c_ini.fecha_hora_conteo)} → {_fmt_dt(c_fin.fecha_hora_conteo)}",
        })

    return tramos


__all__ = ["_calcular_produccion", "_calcular_produccion_rango", "_calcular_tramos"]
