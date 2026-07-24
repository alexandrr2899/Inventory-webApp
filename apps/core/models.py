from django.db import models
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal

from .textnorm import norm


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
    dias_credito = models.PositiveIntegerField(
        default=0, verbose_name='Días de crédito',
        help_text='Días para calcular el vencimiento de facturas y envíos (0 = contado).',
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    @property
    def saldo_a_favor(self):
        """Crédito no aplicado del cliente = Σ pagos − Σ aplicaciones.

        Se resuelve en dos agregados en la BD (independiente del número de
        pagos), evitando el N+1 de iterar `saldo_sin_aplicar` pago por pago.
        """
        _dec = models.DecimalField(max_digits=12, decimal_places=2)
        total_pagos = self.pagos.aggregate(s=Coalesce(
            models.Sum('monto'), models.Value(Decimal('0')), output_field=_dec))['s']
        total_aplicado = AplicacionPago.objects.filter(pago__cliente=self).aggregate(
            s=Coalesce(models.Sum('monto'), models.Value(Decimal('0')),
                       output_field=_dec))['s']
        return total_pagos - total_aplicado

    @property
    def total_adeudado(self):
        """Saldo pendiente total = Σ monto_total − Σ aplicaciones, sobre docs no anulados.

        Equivalente a sumar `saldo_pendiente` por documento, pero en dos
        agregados en la BD en vez de un aggregate por documento (N+1).
        """
        _dec = models.DecimalField(max_digits=12, decimal_places=2)
        docs = self.documentos.exclude(estado_pago='anulada')
        total_docs = docs.aggregate(s=Coalesce(
            models.Sum('monto_total'), models.Value(Decimal('0')), output_field=_dec))['s']
        total_aplicado = AplicacionPago.objects.filter(
            documento__cliente=self,
        ).exclude(documento__estado_pago='anulada').aggregate(
            s=Coalesce(models.Sum('monto'), models.Value(Decimal('0')),
                       output_field=_dec))['s']
        return total_docs - total_aplicado


class ClienteAlias(models.Model):
    """Otro nombre con el que un cliente aparece en los PDFs.

    `alias_norm` es único en TODA la tabla, no por cliente: un alias no puede
    apuntar a dos clientes, porque entonces el emparejado del nombre del archivo
    dejaría de ser determinista.
    """
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='aliases')
    alias = models.CharField(max_length=200)
    alias_norm = models.CharField(max_length=200, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Alias de cliente'
        verbose_name_plural = 'Alias de cliente'
        ordering = ['alias']
        constraints = [
            models.UniqueConstraint(fields=['alias_norm'], name='cliente_alias_norm_unico'),
        ]

    def __str__(self):
        return f'{self.alias} → {self.cliente.nombre}'

    def save(self, *args, **kwargs):
        self.alias = (self.alias or '').strip()
        self.alias_norm = norm(self.alias)
        super().save(*args, **kwargs)


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


class InventarioConfig(models.Model):
    """
    Configuración singleton del inventario (una sola fila, pk=1).
    Por ahora guarda el orden de las tabs de la lista de inventario.
    """
    orden_tabs = models.JSONField(default=list)

    class Meta:
        verbose_name = 'Configuración de inventario'
        verbose_name_plural = 'Configuración de inventario'
        permissions = [
            ('ordenar_tabs_inventario', 'Puede ordenar las tabs del inventario'),
        ]

    def __str__(self):
        return 'Configuración de inventario'


# ─── MÓDULO FACTURAS ──────────────────────────────────────────────────────────


class CategoriaProducto(models.Model):
    nombre = models.CharField(max_length=60)
    palabra_clave = models.CharField(
        max_length=60, blank=True,
        help_text='Si el nombre del archivo la contiene, el envío se clasifica en esta categoría.')
    es_predeterminada = models.BooleanField(
        default=False,
        help_text='Categoría asignada cuando ninguna palabra clave coincide.')
    activa = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)
    color = models.CharField(
        max_length=7, blank=True,
        help_text='Color hex (p. ej. #FFA500) para resaltar la categoría en el estado de cuenta.')

    class Meta:
        verbose_name = 'Categoría de producto'
        verbose_name_plural = 'Categorías de producto'
        ordering = ['orden', 'nombre']
        permissions = [
            ('gestionar_categorias_producto', 'Puede gestionar categorías de producto'),
        ]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.es_predeterminada:
            CategoriaProducto.objects.exclude(pk=self.pk).filter(
                es_predeterminada=True).update(es_predeterminada=False)

    @classmethod
    def predeterminada(cls):
        """Categoría efectiva por defecto: debe estar activa para poder usarse."""
        return cls.objects.filter(es_predeterminada=True, activa=True).first()


class TarifaCliente(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='tarifas')
    categoria = models.ForeignKey(
        'CategoriaProducto', on_delete=models.PROTECT, related_name='tarifas')
    precio_por_libra = models.DecimalField(max_digits=12, decimal_places=2)
    activa = models.BooleanField(default=True)
    fecha_inicio = models.DateField(default=timezone.now)
    fecha_fin = models.DateField(null=True, blank=True)
    notas = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Tarifa de cliente'
        verbose_name_plural = 'Tarifas de cliente'
        ordering = ['cliente', 'categoria', '-fecha_inicio']
        constraints = [
            models.UniqueConstraint(
                fields=['cliente', 'categoria'],
                condition=models.Q(activa=True),
                name='tarifa_unica_activa_por_cliente_categoria',
            ),
        ]

    def __str__(self):
        return f'{self.cliente.nombre} · {self.categoria.nombre} · L {self.precio_por_libra}/lb'

    @classmethod
    def activa_para(cls, cliente, categoria):
        """Tarifa activa vigente del cliente para la categoría, o None."""
        return cls.objects.filter(
            cliente=cliente, categoria=categoria, activa=True,
        ).order_by('-fecha_inicio').first()


class MetodoPago(models.Model):
    TIPO_CHOICES = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia'),
        ('deposito', 'Depósito'),
        ('cheque', 'Cheque'),
        ('tarjeta', 'Tarjeta'),
        ('otro', 'Otro'),
    ]
    nombre = models.CharField(max_length=80)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='otro')
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Método de pago'
        verbose_name_plural = 'Métodos de pago'
        ordering = ['orden', 'nombre']
        permissions = [
            ('gestionar_metodos_pago', 'Puede gestionar métodos de pago'),
        ]

    def __str__(self):
        return self.nombre


class DocumentoFactura(models.Model):
    TIPO_CHOICES = [
        ('factura', 'Factura'),
        ('envio', 'Envío'),
    ]
    ESTADO_REVISION_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('revisada', 'Revisada'),
        ('error', 'Error'),
    ]
    ESTADO_PAGO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('pagada', 'Pagada'),
        ('vencida', 'Vencida'),
        ('anulada', 'Anulada'),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='documentos')
    archivo_pdf = models.FileField(upload_to='facturas/%Y/%m/', null=True, blank=True)
    tipo_documento = models.CharField(max_length=10, choices=TIPO_CHOICES)
    numero_documento = models.CharField(max_length=60, blank=True)
    fecha_documento = models.DateField(null=True, blank=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    categoria = models.ForeignKey(
        'CategoriaProducto', on_delete=models.PROTECT, null=True, blank=True,
        related_name='documentos')

    total_libras = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    precio_por_libra = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    isv = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='ISV')
    monto_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    texto_extraido = models.TextField(blank=True)
    estado_revision = models.CharField(max_length=12, choices=ESTADO_REVISION_CHOICES, default='pendiente')
    estado_pago = models.CharField(max_length=12, choices=ESTADO_PAGO_CHOICES, default='pendiente')
    notas = models.TextField(blank=True)
    subcliente = models.CharField(max_length=120, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Documento de factura'
        verbose_name_plural = 'Documentos de factura'
        ordering = ['-fecha_documento', '-created_at']
        permissions = [
            ('ver_facturas', 'Puede ver el módulo de facturas'),
            ('gestionar_facturas', 'Puede crear y editar documentos de facturas'),
            ('registrar_pago_factura', 'Puede registrar pagos de facturas'),
            ('anular_factura', 'Puede anular documentos de facturas'),
            ('gestionar_tarifas', 'Puede gestionar tarifas de cliente'),
        ]

    def __str__(self):
        return f'{self.get_tipo_documento_display()} {self.numero_documento or self.pk} · {self.cliente.nombre}'

    @staticmethod
    def anotar_pagado(qs):
        """Anota `pagado_ann` (suma de AplicacionPago) en `qs`.

        Cualquier queryset de DocumentoFactura anotado así hace que `monto_pagado`
        y `saldo_pendiente` sean O(1) por fila (una sola consulta agregada en la
        BD), evitando el N+1 al recorrer listas o el estado de cuenta.
        """
        return qs.annotate(pagado_ann=Coalesce(
            models.Sum('aplicaciones__monto'),
            models.Value(Decimal('0')),
            output_field=models.DecimalField(max_digits=12, decimal_places=2),
        ))

    @property
    def monto_pagado(self):
        # Si el queryset anotó `pagado_ann` (ver anotar_pagado) se usa ese valor y
        # se evita un aggregate por fila (N+1) en listas/estados de cuenta.
        if 'pagado_ann' in self.__dict__:
            return self.__dict__['pagado_ann'] or Decimal('0.00')
        total = self.aplicaciones.aggregate(s=models.Sum('monto'))['s']
        return total if total is not None else Decimal('0.00')

    @property
    def saldo_pendiente(self):
        return (self.monto_total or 0) - self.monto_pagado

    @property
    def es_pago_parcial(self):
        return self.monto_pagado > 0 and self.saldo_pendiente > 0

    @property
    def vence_hoy(self):
        return bool(self.fecha_vencimiento) and self.fecha_vencimiento == timezone.localdate()

    @property
    def vence_en_7_dias(self):
        if not self.fecha_vencimiento:
            return False
        delta = (self.fecha_vencimiento - timezone.localdate()).days
        return 0 <= delta <= 7

    @property
    def esta_vencida(self):
        """Vencida de forma dinámica: con saldo, pasada la fecha y no anulada.

        No depende de que ``estado_pago`` esté recalculado (evita necesitar un cron).
        """
        return (
            self.estado_pago != 'anulada'
            and bool(self.fecha_vencimiento)
            and self.fecha_vencimiento < timezone.localdate()
            and self.saldo_pendiente > 0
        )

    @property
    def dias_atraso(self):
        """Días de atraso si está vencida; 0 en otro caso."""
        if not self.esta_vencida:
            return 0
        return (timezone.localdate() - self.fecha_vencimiento).days

    @property
    def dias_para_vencer(self):
        """Días que faltan para el vencimiento (None si no aplica o ya venció/pagó)."""
        if (self.estado_pago in ('anulada', 'pagada') or not self.fecha_vencimiento
                or self.saldo_pendiente <= 0):
            return None
        delta = (self.fecha_vencimiento - timezone.localdate()).days
        return delta if delta >= 0 else None


class Pago(models.Model):
    """Abono de un cliente; se reparte entre facturas vía AplicacionPago."""
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='pagos')
    fecha_pago = models.DateField(default=timezone.now)
    metodo_pago = models.ForeignKey('MetodoPago', on_delete=models.PROTECT, related_name='pagos')
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    referencia = models.CharField(max_length=120, blank=True)
    comprobante = models.FileField(upload_to='facturas/pagos/%Y/%m/', null=True, blank=True)
    notas = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'
        ordering = ['-fecha_pago', '-created_at']
        constraints = [
            models.CheckConstraint(check=models.Q(monto__gt=0), name='pago_monto_positivo'),
        ]

    def __str__(self):
        return f'Abono L {self.monto} · {self.cliente.nombre}'

    @property
    def monto_aplicado(self):
        total = self.aplicaciones.aggregate(s=models.Sum('monto'))['s']
        return total if total is not None else Decimal('0.00')

    @property
    def saldo_sin_aplicar(self):
        return self.monto - self.monto_aplicado


class AplicacionPago(models.Model):
    """Porción de un Pago aplicada a una factura concreta."""
    pago = models.ForeignKey(Pago, on_delete=models.CASCADE, related_name='aplicaciones')
    documento = models.ForeignKey(DocumentoFactura, on_delete=models.PROTECT, related_name='aplicaciones')
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Aplicación de pago'
        verbose_name_plural = 'Aplicaciones de pago'
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(check=models.Q(monto__gt=0), name='aplicacion_monto_positivo'),
        ]

    def __str__(self):
        return f'L {self.monto} → {self.documento}'
