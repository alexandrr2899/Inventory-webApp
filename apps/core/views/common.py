"""
common.py — Imports compartidos, constantes y helpers genéricos de las vistas.

Actúa como "barrel": expone todo su namespace vía `from .common import *`
(incluye helpers con prefijo _ gracias a __all__ al final del módulo).
Los módulos de vistas hacen `from .common import *` para tener Django, modelos,
forms, servicios y helpers disponibles sin reimportar.
"""

import logging
import os
import subprocess
import time
from functools import wraps
from pathlib import Path

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_POST
from django.db.models import Sum, Q, Count, F, Value, DecimalField
from django.db.models.functions import Coalesce
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.core.paginator import Paginator
from django.core.cache import cache
from django.urls import reverse
from datetime import date, timedelta, datetime as dt_datetime, time as dt_time
from decimal import Decimal
import csv
import io
import json

from django.contrib.auth.models import User, Group

from ..models import (
    Item, Categoria, Ubicacion, Stock, Maquina, Cliente,
    MovimientoInventario, DetalleMovimiento, Conteo, ConteoDetalle, BackupJob,
)
from ..forms import (
    ItemForm, CategoriaForm, UbicacionForm, MaquinaForm, ClienteForm,
    MovimientoEntradaForm, MovimientoSalidaForm, MovimientoTransferenciaForm,
    ConteoForm, FiltroMovimientosForm, ProduccionForm, ImportarItemsForm,
    UsuarioCrearForm, UsuarioEditarForm,
)
from ..services.notifications import notify_stock, send_event, send_security_event

security_log = logging.getLogger('security')
perf_log = logging.getLogger('performance')
event_log = logging.getLogger('events')

# Anotación compartida: stock total por ítem
_STOCK_ANN = Coalesce(
    Sum('stock__cantidad_actual'),
    Value(Decimal('0')),
    output_field=DecimalField(max_digits=12, decimal_places=2),
)


def _perm(codename):
    """Shorthand permission string for core app."""
    return f'core.{codename}'


def _json_safe(data):
    """
    JSON seguro para incrustar dentro de <script>.
    Evita que valores con </script>, <, > o & rompan el bloque JS.
    """
    return (
        json.dumps(data)
        .replace('&', '\\u0026')
        .replace('<', '\\u003C')
        .replace('>', '\\u003E')
    )


def _get_client_ip(request):
    """Return real client IP, respecting X-Forwarded-For from Cloudflare Tunnel."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def _timed_view(name):
    """Log elapsed time for high-traffic views without changing responses."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            start = time.monotonic()
            try:
                return view_func(request, *args, **kwargs)
            finally:
                elapsed = time.monotonic() - start
                user = request.user.username if request.user.is_authenticated else 'anon'
                perf_log.info('%s %.3fs user=%s path=%s', name, elapsed, user, request.get_full_path())
        return wrapper
    return decorator


def _rango_local_dia(fecha):
    tz = timezone.get_current_timezone()
    inicio = timezone.make_aware(dt_datetime.combine(fecha, dt_time.min), tz)
    return inicio, inicio + timedelta(days=1)


def _filtro_detalle_camiseta():
    return (
        Q(item__tipo='producto')
        & (
            Q(item__categoria__nombre__icontains='camiseta')
            | Q(item__nombre__icontains='camiseta')
        )
    )


def _calcular_salidas_camiseta_del_dia(fecha):
    inicio, fin = _rango_local_dia(fecha)
    qs = (
        DetalleMovimiento.objects
        .filter(
            movimiento__tipo_movimiento='salida',
            movimiento__anulado=False,
            movimiento__eliminado=False,
            movimiento__fecha_movimiento__gte=inicio,
            movimiento__fecha_movimiento__lt=fin,
        )
        .filter(_filtro_detalle_camiseta())
    )
    return {
        'total': qs.aggregate(t=Sum('cantidad'))['t'] or Decimal('0'),
        'movimientos': qs.values('movimiento_id').distinct().count(),
        'productos': qs.values('item_id').distinct().count(),
        'inicio': inicio,
        'fin': fin,
    }


# Barrel: exporta TODO el namespace (incluye helpers _ y los imports) para
# que `from .common import *` los traiga a los módulos de vistas.
__all__ = [name for name in dir() if not name.startswith('__')]
