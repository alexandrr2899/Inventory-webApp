from django.db import models
from django.db.models import Q
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
    orden  = models.PositiveIntegerField(
        default=0,
        verbose_name='Orden',
        help_text='Posición en listados. 0 = sin orden definido (usa nombre como fallback).',
    )

    class Meta:
        verbose_name = 'Ítem'
        verbose_name_plural = 'Ítems'
        ordering = ['orden', 'nombre']
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


class BackupJob(models.Model):
    ESTADO_CHOICES = [
        ('ejecutando', 'Ejecutando'),
        ('exitoso', 'Exitoso'),
        ('fallido', 'Fallido'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    fecha_inicio = models.DateTimeField(default=timezone.now)
    fecha_fin = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='ejecutando')
    archivo = models.CharField(max_length=255, blank=True)
    tamano = models.PositiveBigIntegerField(default=0)
    mensaje_error = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Trabajo de backup'
        verbose_name_plural = 'Trabajos de backup'
        ordering = ['-fecha_inicio']
        permissions = [
            ('gestionar_backups', 'Puede gestionar backups'),
        ]

    def __str__(self):
        return f'Backup {self.get_estado_display()} - {timezone.localtime(self.fecha_inicio):%d/%m/%Y %H:%M}'


class MovimientoInventario(models.Model):
    TIPO_CHOICES = [
        ('entrada', 'Entrada'),
        ('salida', 'Salida'),
        ('ajuste', 'Ajuste'),
        ('transferencia', 'Transferencia'),
    ]

    TIPO_SALIDA_CHOICES = [
        ('producto_terminado', 'Producto Terminado'),
        ('repuestos',          'Repuestos'),
        ('consumibles',        'Consumibles'),
        ('otros',              'Otros'),
    ]

    fecha = models.DateTimeField(default=timezone.now, verbose_name='Fecha registro')
    # Cuándo ocurrió realmente el movimiento (puede ser anterior a la fecha de registro)
    fecha_movimiento = models.DateTimeField(
        default=timezone.now,
        verbose_name='Fecha del movimiento',
    )
    tipo_movimiento = models.CharField(max_length=20, choices=TIPO_CHOICES, verbose_name='Tipo')
    # Subcategoría de salida (solo cuando tipo_movimiento='salida')
    tipo_salida = models.CharField(
        max_length=30, choices=TIPO_SALIDA_CHOICES, blank=True, default='',
        verbose_name='Tipo de salida',
    )
    motivo = models.TextField(blank=True)
    usuario = models.ForeignKey(User, on_delete=models.PROTECT)
    # Cliente a nivel de cabecera (para salidas de producto terminado)
    cliente = models.ForeignKey(
        'Cliente', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movimientos_cabecera', verbose_name='Cliente',
    )

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
            models.Index(fields=['fecha_movimiento'],           name='mov_fecha_mov_idx'),
            models.Index(fields=['tipo_movimiento', 'fecha_movimiento'], name='mov_tipo_fecha_idx'),
            models.Index(fields=['anulado', 'eliminado'],       name='mov_estado_idx'),
        ]
        permissions = [
            ('editar_movimiento',   'Puede editar movimientos'),
            ('anular_movimiento',   'Puede anular movimientos'),
            ('eliminar_movimiento', 'Puede eliminar movimientos (lógico)'),
        ]

    def __str__(self):
        n = self.detalles.count() if self.pk else 0
        fecha_local = timezone.localtime(self.fecha_movimiento)
        return f'{self.get_tipo_movimiento_display()} #{self.pk} ({n} ítem(s)) · {fecha_local.strftime("%d/%m/%Y")}'


class DetalleMovimiento(models.Model):
    """
    Línea de ítem dentro de un MovimientoInventario.
    Un movimiento cabecera puede tener N detalles (uno por ítem).
    """
    movimiento = models.ForeignKey(
        MovimientoInventario, on_delete=models.CASCADE,
        related_name='detalles', verbose_name='Movimiento',
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    ubicacion_origen = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, null=True, blank=True,
        related_name='detalles_origen', verbose_name='Ubicación origen',
    )
    ubicacion_destino = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, null=True, blank=True,
        related_name='detalles_destino', verbose_name='Ubicación destino',
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.SET_NULL, null=True, blank=True,
    )
    maquina = models.ForeignKey(
        Maquina, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name='Máquina',
    )
    # Conciliación: marca que la salida se registró con stock negativo
    pendiente_conciliacion = models.BooleanField(
        default=False,
        verbose_name='Pendiente conciliación',
        help_text='True cuando la salida se aprobó con stock insuficiente y aún no se ha conciliado.',
    )
    fecha_conciliacion = models.DateTimeField(
        null=True, blank=True,
        verbose_name='Fecha de conciliación',
    )

    class Meta:
        verbose_name = 'Línea de movimiento'
        verbose_name_plural = 'Líneas de movimiento'
        ordering = ['id']
        indexes = [
            models.Index(fields=['item', 'movimiento'], name='det_item_mov_idx'),
            models.Index(fields=['ubicacion_origen'], name='det_ub_orig_idx'),
            models.Index(fields=['ubicacion_destino'], name='det_ub_dest_idx'),
            models.Index(fields=['pendiente_conciliacion'], name='det_pend_conc_idx'),
        ]

    def __str__(self):
        return f'{self.item.nombre} × {self.cantidad}'


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
    TIPO_CONTEO_CHOICES = [
        ('camiseta', 'Camiseta'),
        ('pigmentos', 'Pigmentos'),
        ('lisa', 'Lisa'),
        ('otros', 'Otros'),
    ]

    fecha = models.DateField()
    turno = models.CharField(max_length=10, choices=TURNO_CHOICES)
    tipo_conteo = models.CharField(
        max_length=20, choices=TIPO_CONTEO_CHOICES, default='otros',
        verbose_name='Tipo de conteo',
    )
    fecha_hora_conteo = models.DateTimeField(
        default=timezone.now,
        verbose_name='Fecha y hora del conteo',
    )
    usuario = models.ForeignKey(User, on_delete=models.PROTECT)
    observaciones = models.TextField(blank=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente')
    creado_en = models.DateTimeField(auto_now_add=True)

    # Anulación lógica
    anulado = models.BooleanField(default=False)
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    usuario_anulacion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conteos_anulados',
    )
    motivo_anulacion = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Conteo'
        verbose_name_plural = 'Conteos'
        ordering = ['-fecha', 'turno']
        indexes = [
            models.Index(fields=['fecha', 'turno', 'tipo_conteo', 'anulado'], name='conteo_fecha_tipo_idx'),
            models.Index(fields=['estado', 'anulado'], name='conteo_estado_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['fecha', 'turno', 'tipo_conteo'],
                condition=Q(anulado=False),
                name='conteo_activo_unico',
            )
        ]
        permissions = [
            ('editar_conteo', 'Puede editar conteos'),
            ('anular_conteo', 'Puede anular conteos'),
        ]

    def __str__(self):
        return f'Conteo {self.get_tipo_conteo_display()} - {self.get_turno_display()} - {self.fecha}'

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
