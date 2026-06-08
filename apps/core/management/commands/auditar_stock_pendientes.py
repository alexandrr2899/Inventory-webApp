"""
Auditoría de stock para salidas de producto terminado y detección de
"drift" de inventario causado por salidas que históricamente NO descontaron
stock (bug previo: _aplicar_efecto_detalle saltaba el descuento cuando no
existía fila Stock en la ubicación de origen).

NO aplica cambios automáticamente. Por defecto es solo-lectura.
Con --fix --confirm corrige el stock al valor esperado recalculado desde
los movimientos activos (no anulados / no eliminados).

Uso:
    python manage.py auditar_stock_pendientes
    python manage.py auditar_stock_pendientes --solo-drift
    python manage.py auditar_stock_pendientes --fix --confirm
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.models import (
    DetalleMovimiento, Stock, MovimientoInventario,
)


class Command(BaseCommand):
    help = (
        'Audita salidas de producto terminado pendientes de conciliación y '
        'detecta diferencias entre el stock registrado y el stock esperado '
        'recalculado desde los movimientos activos. No aplica cambios sin --fix --confirm.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix', action='store_true',
            help='Corrige el stock al valor esperado. Requiere también --confirm.',
        )
        parser.add_argument(
            '--confirm', action='store_true',
            help='Confirmación explícita para aplicar cambios (junto con --fix).',
        )
        parser.add_argument(
            '--solo-drift', action='store_true',
            help='Omite el listado de pendientes; muestra solo el drift de stock.',
        )

    # ──────────────────────────────────────────────────────────────────────────
    def handle(self, *args, **opts):
        fix         = opts['fix']
        confirm     = opts['confirm']
        solo_drift  = opts['solo_drift']

        if not solo_drift:
            self._reporte_pendientes()

        drift = self._calcular_drift()
        self._reporte_drift(drift)

        if fix:
            if not confirm:
                self.stdout.write(self.style.WARNING(
                    '\n⚠️  --fix requiere --confirm. No se aplicó ningún cambio.'
                ))
                return
            if not drift:
                self.stdout.write(self.style.SUCCESS(
                    '\nNo hay drift que corregir. Stock consistente.'
                ))
                return
            self._aplicar_fix(drift)

    # ──────────────────────────────────────────────────────────────────────────
    def _reporte_pendientes(self):
        """Sección A: salidas producto terminado pendientes de conciliación."""
        pendientes = (
            DetalleMovimiento.objects
            .filter(
                movimiento__tipo_movimiento='salida',
                movimiento__tipo_salida='producto_terminado',
                movimiento__anulado=False,
                movimiento__eliminado=False,
                pendiente_conciliacion=True,
                cantidad__gt=0,
            )
            .select_related('movimiento', 'item', 'ubicacion_origen', 'cliente')
            .order_by('movimiento__fecha_movimiento')
        )

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n═══ A. Salidas PT pendientes de conciliación ═══'
        ))
        if not pendientes:
            self.stdout.write('  (ninguna)')
            return

        self.stdout.write(
            f'  {"Mov":>5}  {"Ítem":<28} {"Cant":>8}  {"Stock act.":>10}  '
            f'{"Cliente":<18} {"Fecha":<16}'
        )
        for det in pendientes:
            mov = det.movimiento
            stock_obj = Stock.objects.filter(
                item=det.item, ubicacion=det.ubicacion_origen
            ).first()
            stock_act = stock_obj.cantidad_actual if stock_obj else Decimal('0')
            cliente = (det.cliente.nombre if det.cliente
                       else (mov.cliente.nombre if mov.cliente else '—'))
            self.stdout.write(
                f'  #{mov.pk:>4}  {det.item.nombre[:28]:<28} '
                f'{det.cantidad:>8} '
                f'{stock_act:>10}  '
                f'{cliente[:18]:<18} '
                f'{timezone.localtime(mov.fecha_movimiento):%d/%m/%Y %H:%M}'
            )
        self.stdout.write(self.style.NOTICE(
            f'  Total pendientes: {pendientes.count()}'
        ))

    # ──────────────────────────────────────────────────────────────────────────
    def _calcular_drift(self):
        """
        Recalcula el stock esperado por (item, ubicacion) desde todos los
        movimientos activos y lo compara con la tabla Stock.

        Devuelve lista de dicts con diferencias:
            {item, ubicacion, esperado, actual, diff}
        """
        esperado: dict = {}  # (item_id, ub_id) → Decimal

        def _add(item_id, ub_id, delta):
            if ub_id is None:
                return
            key = (item_id, ub_id)
            esperado[key] = esperado.get(key, Decimal('0')) + delta

        dets = (
            DetalleMovimiento.objects
            .filter(movimiento__anulado=False, movimiento__eliminado=False)
            .select_related('movimiento')
            .only(
                'item_id', 'cantidad',
                'ubicacion_origen_id', 'ubicacion_destino_id',
                'movimiento__tipo_movimiento',
            )
        )
        for det in dets:
            t = det.movimiento.tipo_movimiento
            if t == 'entrada':
                _add(det.item_id, det.ubicacion_destino_id, det.cantidad)
            elif t == 'salida':
                _add(det.item_id, det.ubicacion_origen_id, -det.cantidad)
            elif t == 'ajuste':
                _add(det.item_id, det.ubicacion_destino_id, det.cantidad)
            elif t == 'transferencia':
                _add(det.item_id, det.ubicacion_origen_id, -det.cantidad)
                _add(det.item_id, det.ubicacion_destino_id, det.cantidad)

        # Stock actual
        actual: dict = {}
        for s in Stock.objects.all().only('item_id', 'ubicacion_id', 'cantidad_actual'):
            actual[(s.item_id, s.ubicacion_id)] = s.cantidad_actual

        # Comparar (unión de claves)
        drift = []
        all_keys = set(esperado) | set(actual)
        for key in all_keys:
            exp = esperado.get(key, Decimal('0'))
            act = actual.get(key, Decimal('0'))
            if exp != act:
                drift.append({
                    'item_id': key[0],
                    'ubicacion_id': key[1],
                    'esperado': exp,
                    'actual': act,
                    'diff': exp - act,
                })
        return drift

    # ──────────────────────────────────────────────────────────────────────────
    def _reporte_drift(self, drift):
        """Sección B: diferencias stock registrado vs esperado."""
        from apps.core.models import Item, Ubicacion

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n═══ B. Drift de stock (esperado vs registrado) ═══'
        ))
        if not drift:
            self.stdout.write(self.style.SUCCESS(
                '  ✓ Stock consistente con los movimientos activos.'
            ))
            return

        items = {i.pk: i for i in Item.objects.filter(
            pk__in=[d['item_id'] for d in drift])}
        ubs = {u.pk: u for u in Ubicacion.objects.filter(
            pk__in=[d['ubicacion_id'] for d in drift])}

        self.stdout.write(
            f'  {"Ítem":<28} {"Ubicación":<18} {"Esperado":>10} '
            f'{"Registrado":>11} {"Diff":>9}'
        )
        for d in sorted(drift, key=lambda x: abs(x['diff']), reverse=True):
            item = items.get(d['item_id'])
            ub = ubs.get(d['ubicacion_id'])
            nombre = item.nombre if item else f'#{d["item_id"]}'
            ubn = ub.nombre if ub else f'#{d["ubicacion_id"]}'
            self.stdout.write(
                f'  {nombre[:28]:<28} {ubn[:18]:<18} '
                f'{d["esperado"]:>10} {d["actual"]:>11} '
                + self.style.ERROR(f'{d["diff"]:>+9}')
            )
        self.stdout.write(self.style.WARNING(
            f'  Total con diferencia: {len(drift)} ubicación(es) de ítem.\n'
            f'  Para corregir: python manage.py auditar_stock_pendientes --fix --confirm'
        ))

    # ──────────────────────────────────────────────────────────────────────────
    def _aplicar_fix(self, drift):
        """Corrige el stock al valor esperado. Solo con --fix --confirm."""
        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n═══ Aplicando corrección de stock ═══'
        ))
        n = 0
        with transaction.atomic():
            for d in drift:
                stock, _ = Stock.objects.get_or_create(
                    item_id=d['item_id'], ubicacion_id=d['ubicacion_id'],
                    defaults={'cantidad_actual': Decimal('0')},
                )
                stock.cantidad_actual = d['esperado']
                stock.save(update_fields=['cantidad_actual'])
                n += 1
        self.stdout.write(self.style.SUCCESS(
            f'  ✓ {n} fila(s) de Stock corregida(s) al valor esperado.'
        ))
