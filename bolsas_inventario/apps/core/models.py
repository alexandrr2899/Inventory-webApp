from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal


class Categoria(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Item(models.Model):
    TIPO_CHOICES = [
        ('producto', 'Producto Terminado'),
        ('repuesto', 'Repuesto'),
        ('consumible', 'Consumible'),
    ]

    codigo = models.CharField(max_length=50, unique=True, verbose_name='Código')
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, verbose_name='Descripción')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    categoria = models.ForeignKey(
        Categoria, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name='Categoría'
    )
    unidad_medida = models.CharField(max_length=30, verbose_name='Unidad de medida')
    stock_minimo = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name='Stock mínimo'
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Ítem'
        verbose_name_plural = 'Ítems'
        ordering = ['nombre']
        indexes = [
            models.Index(fields=['activo', 'tipo'], name='item_activo_tipo_idx'),
        ]
        permissions = [
            ('ver_inventario',       'Puede ver el inventario'),
            ('crear_item',           'Puede crear ítems'),
            ('editar_item',          'Puede editar ítems'),
            ('registrar_entrada',    'Puede registrar entradas'),
            ('registrar_salida',     'Puede registrar salidas'),
            ('registrar_conteo',     'Puede registrar conteos físicos'),
            ('aplicar_conciliacion', 'Puede aplicar conciliación'),
            ('importar_excel',       'Puede importar ítems desde Excel'),
            ('ver_reportes',         'Puede ver reportes'),
            ('registrar_produccion', 'Puede registrar producción'),
        ]

    def __str__(self):
        return f'{self.codigo} - {self.nombre}'

    def stock_total(self):
        resultado = self.stock_set.aggregate(total=models.Sum('cantidad_actual'))
        return resultado['total'] or Decimal('0')

    def bajo_stock(self):
        return self.stock_total() <= self.stock_minimo


class Ubicacion(models.Model):
    TIPO_CHOICES = [
        ('bodega', 'Bodega'),
        ('produccion', 'Producción'),
        ('estante', 'Estante'),
        ('gaveta', 'Gaveta'),
    ]

    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    descripcion = models.TextField(blank=True, verbose_name='Descripción')

    class Meta:
        verbose_name = 'Ubicación'
        verbose_name_plural = 'Ubicaciones'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.nombre} ({self.get_tipo_display()})'


class Stock(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.CASCADE, verbose_name='Ubicación')
    cantidad_actual = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Stock'
        verbose_name_plural = 'Stock'
        unique_together = ['item', 'ubicacion']

    def __str__(self):
        return f'{self.item.nombre} en {self.ubicacion.nombre}: {self.cantidad_actual}'


class Maquina(models.Model):
    codigo = models.CharField(max_length=50, unique=True, verbose_name='Código')
    nombre = models.CharField(max_length=200)
    area = models.CharField(max_length=100, verbose_name='Área')
    descripcion = models.TextField(blank=True, verbose_name='Descripción')
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Máquina'
        verbose_name_plural = 'Máquinas'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.codigo} - {self.nombre}'


class Cliente(models.Model):
    nombre = models.CharField(max_length=200)
    telefono = models.CharField(max_length=20, blank=True)
    rtn = models.CharField(max_length=20, blank=True, verbose_name='RTN')
    direccion = models.TextField(blank=True, verbose_name='Dirección')
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class MovimientoInventario(models.Model):
    TIPO_CHOICES = [
        ('entrada', 'Entrada'),
        ('salida', 'Salida'),
        ('ajuste', 'Ajuste'),
        ('transferencia', 'Transferencia'),
    ]

    fecha = models.DateTimeField(default=timezone.now, verbose_name='Fecha registro')
    # Cuándo ocurrió realmente el movimiento (puede ser anterior a la fecha de registro)
    fecha_movimiento = models.DateTimeField(
        default=timezone.now,
        verbose_name='Fecha del movimiento',
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    tipo_movimiento = models.CharField(max_length=20, choices=TIPO_CHOICES, verbose_name='Tipo')
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    ubicacion_origen = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, null=True, blank=True,
        related_name='movimientos_origen', verbose_name='Ubicación origen'
    )
    ubicacion_destino = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, null=True, blank=True,
        related_name='movimientos_destino', verbose_name='Ubicación destino'
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.SET_NULL, null=True, blank=True
    )
    maquina = models.ForeignKey(
        Maquina, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name='Máquina'
    )
    motivo = models.TextField(blank=True)
    usuario = models.ForeignKey(User, on_delete=models.PROTECT)

    # ── Auditoría de edición ──────────────────────────────────────────────────
    editado = models.BooleanField(default=False)
    fecha_edicion = models.DateTimeField(null=True, blank=True)
    usuario_edicion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movimientos_editados',
    )
    motivo_edicion = models.TextField(blank=True)

    # ── Auditoría de anulación ────────────────────────────────────────────────
    anulado = models.BooleanField(default=False)
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    usuario_anulacion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movimientos_anulados',
    )
    motivo_anulacion = models.TextField(blank=True)

    # ── Eliminación lógica ────────────────────────────────────────────────────
    eliminado = models.BooleanField(default=False)
    fecha_eliminacion = models.DateTimeField(null=True, blank=True)
    usuario_eliminacion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movimientos_eliminados',
    )
    motivo_eliminacion = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Movimiento'
        verbose_name_plural = 'Movimientos'
        ordering = ['-fecha']
        indexes = [
            models.Index(fields=['fecha_movimiento'], name='mov_fecha_mov_idx'),
            models.Index(fields=['item', 'tipo_movimiento'], name='mov_item_tipo_idx'),
            models.Index(fields=['tipo_movimiento', 'fecha_movimiento'], name='mov_tipo_fecha_idx'),
            models.Index(fields=['anulado', 'eliminado'], name='mov_estado_idx'),
        ]
        permissions = [
            ('editar_movimiento',   'Puede editar movimientos'),
            ('anular_movimiento',   'Puede anular movimientos'),
            ('eliminar_movimiento', 'Puede eliminar movimientos (lógico)'),
        ]

    def __str__(self):
        return f'{self.get_tipo_movimiento_display()} - {self.item.nombre} ({self.cantidad})'

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            self._actualizar_stock()

    def _actualizar_stock(self):
        if self.tipo_movimiento == 'entrada':
            stock, _ = Stock.objects.get_or_create(
                item=self.item,
                ubicacion=self.ubicacion_destino,
                defaults={'cantidad_actual': Decimal('0')}
            )
            stock.cantidad_actual += self.cantidad
            stock.save()

        elif self.tipo_movimiento == 'salida':
            try:
                stock = Stock.objects.get(item=self.item, ubicacion=self.ubicacion_origen)
                stock.cantidad_actual -= self.cantidad
                stock.save()
            except Stock.DoesNotExist:
                pass

        elif self.tipo_movimiento == 'transferencia':
            try:
                stock_origen = Stock.objects.get(item=self.item, ubicacion=self.ubicacion_origen)
                stock_origen.cantidad_actual -= self.cantidad
                stock_origen.save()
            except Stock.DoesNotExist:
                pass
            stock_destino, _ = Stock.objects.get_or_create(
                item=self.item,
                ubicacion=self.ubicacion_destino,
                defaults={'cantidad_actual': Decimal('0')}
            )
            stock_destino.cantidad_actual += self.cantidad
            stock_destino.save()

        elif self.tipo_movimiento == 'ajuste':
            # cantidad puede ser positiva (sobrante) o negativa (faltante)
            stock, _ = Stock.objects.get_or_create(
                item=self.item,
                ubicacion=self.ubicacion_destino,
                defaults={'cantidad_actual': Decimal('0')}
            )
            stock.cantidad_actual += self.cantidad
            stock.save()


class Conteo(models.Model):
    TURNO_CHOICES = [
        ('manana', 'Mañana'),
        ('tarde', 'Tarde'),
    ]
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('parcial', 'Parcial'),
        ('conciliado', 'Conciliado'),
    ]

    fecha = models.DateField()
    turno = models.CharField(max_length=10, choices=TURNO_CHOICES)
    # Cuándo ocurrió físicamente el conteo (puede diferir de creado_en)
    fecha_hora_conteo = models.DateTimeField(
        default=timezone.now,
        verbose_name='Fecha y hora del conteo',
    )
    usuario = models.ForeignKey(User, on_delete=models.PROTECT)
    observaciones = models.TextField(blank=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Conteo'
        verbose_name_plural = 'Conteos'
        ordering = ['-fecha', 'turno']
        unique_together = ['fecha', 'turno']

    def __str__(self):
        return f'Conteo {self.get_turno_display()} - {self.fecha}'

    def actualizar_estado(self):
        detalles = self.detalles.all()
        if not detalles.exists():
            self.estado = 'pendiente'
            self.save(update_fields=['estado'])
            return
        pendientes = detalles.filter(
            ajuste_aplicado=False, diferencia_final__isnull=False
        ).exclude(diferencia_final=0).count()
        aplicados = detalles.filter(ajuste_aplicado=True).count()
        sin_diferencia = detalles.filter(diferencia_final=0).count()
        calculados = detalles.filter(diferencia_final__isnull=False).count()

        if calculados == 0:
            self.estado = 'pendiente'
        elif pendientes == 0:
            self.estado = 'conciliado'
        elif aplicados > 0:
            self.estado = 'parcial'
        else:
            self.estado = 'pendiente'
        self.save(update_fields=['estado'])


class ConteoDetalle(models.Model):
    conteo = models.ForeignKey(Conteo, on_delete=models.CASCADE, related_name='detalles')
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, verbose_name='Ubicación')
    cantidad_contada = models.DecimalField(max_digits=12, decimal_places=2)
    cantidad_sistema_al_conteo = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'),
        verbose_name='Sistema al conteo'
    )
    diferencia_original = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'),
        verbose_name='Diferencia original'
    )
    # Calculado durante conciliación (incorpora movimientos atrasados)
    diferencia_final = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='Diferencia final'
    )
    ajuste_aplicado = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Detalle de Conteo'
        verbose_name_plural = 'Detalles de Conteo'

    def __str__(self):
        return f'{self.item.nombre}: contado={self.cantidad_contada}, sistema={self.cantidad_sistema_al_conteo}'

    def save(self, *args, **kwargs):
        self.diferencia_original = self.cantidad_contada - self.cantidad_sistema_al_conteo
        super().save(*args, **kwargs)

    @property
    def estado_badge(self):
        if self.ajuste_aplicado:
            return 'ajustado'
        if self.diferencia_final is None:
            return 'pendiente'
        if self.diferencia_final == 0:
            return 'ok'
        return 'sobrante' if self.diferencia_final > 0 else 'faltante'
