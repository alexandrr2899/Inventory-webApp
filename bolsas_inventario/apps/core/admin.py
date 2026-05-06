from django.contrib import admin
from .models import (
    Categoria, Item, Ubicacion, Stock, Maquina, Cliente,
    MovimientoInventario, DetalleMovimiento, Conteo, ConteoDetalle
)

admin.site.site_header = "Transformadora de Empaques"
admin.site.site_title  = "Transformadora"
admin.site.index_title = "Panel de Administración"


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ['nombre']
    search_fields = ['nombre']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display       = ['codigo', 'orden', 'nombre', 'tipo', 'categoria', 'unidad_medida', 'stock_minimo', 'activo']
    list_display_links = ['codigo']
    list_filter        = ['tipo', 'categoria', 'activo']
    search_fields      = ['codigo', 'nombre']
    list_editable      = ['orden', 'activo']
    ordering           = ['orden', 'nombre']


@admin.register(Ubicacion)
class UbicacionAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'tipo', 'descripcion']
    list_filter = ['tipo']
    search_fields = ['nombre']


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['item', 'ubicacion', 'cantidad_actual']
    list_filter = ['ubicacion']
    search_fields = ['item__nombre', 'item__codigo']
    raw_id_fields = ['item']


@admin.register(Maquina)
class MaquinaAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'nombre', 'area', 'activo']
    list_filter = ['area', 'activo']
    search_fields = ['codigo', 'nombre']
    list_editable = ['activo']


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'telefono', 'rtn', 'activo']
    list_filter = ['activo']
    search_fields = ['nombre', 'rtn']
    list_editable = ['activo']


class ConteoDetalleInline(admin.TabularInline):
    model = ConteoDetalle
    extra = 0
    readonly_fields = ['diferencia_original', 'diferencia_final', 'ajuste_aplicado']


@admin.register(Conteo)
class ConteoAdmin(admin.ModelAdmin):
    list_display = ['fecha', 'turno', 'usuario', 'estado', 'fecha_hora_conteo', 'creado_en']
    list_filter = ['turno', 'estado']
    search_fields = ['fecha']
    inlines = [ConteoDetalleInline]


class DetalleMovimientoInline(admin.TabularInline):
    model = DetalleMovimiento
    extra = 0
    readonly_fields = ['item', 'cantidad', 'ubicacion_origen', 'ubicacion_destino',
                       'cliente', 'maquina']
    can_delete = False


@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(admin.ModelAdmin):
    list_display  = ['pk', 'fecha_movimiento', 'tipo_movimiento', 'tipo_salida',
                     'cliente', 'num_items', 'usuario', 'anulado', 'eliminado']
    list_filter   = ['tipo_movimiento', 'tipo_salida', 'anulado', 'eliminado', 'fecha_movimiento']
    search_fields = ['motivo', 'usuario__username', 'cliente__nombre']
    date_hierarchy = 'fecha_movimiento'
    readonly_fields = ['fecha', 'usuario', 'editado', 'fecha_edicion', 'usuario_edicion',
                       'anulado', 'fecha_anulacion', 'usuario_anulacion',
                       'eliminado', 'fecha_eliminacion', 'usuario_eliminacion']
    inlines = [DetalleMovimientoInline]

    @admin.display(description='Ítems')
    def num_items(self, obj):
        return obj.detalles.count()


class DetalleMovimientoAdmin(admin.ModelAdmin):
    list_display  = ['movimiento', 'item', 'cantidad', 'pendiente_conciliacion', 'fecha_conciliacion']
    list_filter   = ['pendiente_conciliacion']
    search_fields = ['item__nombre', 'item__codigo']

admin.site.register(DetalleMovimiento, DetalleMovimientoAdmin)
