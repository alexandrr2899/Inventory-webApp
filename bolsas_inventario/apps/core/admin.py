from django.contrib import admin
from .models import (
    Categoria, Item, Ubicacion, Stock, Maquina, Cliente,
    MovimientoInventario, Conteo, ConteoDetalle
)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ['nombre']
    search_fields = ['nombre']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'nombre', 'tipo', 'categoria', 'unidad_medida', 'stock_minimo', 'activo']
    list_filter = ['tipo', 'categoria', 'activo']
    search_fields = ['codigo', 'nombre']
    list_editable = ['activo']


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


@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(admin.ModelAdmin):
    list_display = ['fecha_movimiento', 'fecha', 'tipo_movimiento', 'item', 'cantidad',
                    'ubicacion_origen', 'ubicacion_destino', 'usuario']
    list_filter = ['tipo_movimiento', 'fecha_movimiento']
    search_fields = ['item__nombre', 'item__codigo', 'motivo']
    date_hierarchy = 'fecha_movimiento'
    raw_id_fields = ['item']
