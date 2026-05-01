from django.urls import path
from . import views

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Inventario - Items
    path('inventario/', views.inventario_lista, name='inventario_lista'),
    path('inventario/nuevo/', views.item_crear, name='item_crear'),
    path('inventario/<int:pk>/', views.item_detalle, name='item_detalle'),
    path('inventario/<int:pk>/editar/', views.item_editar, name='item_editar'),
    path('inventario/<int:pk>/toggle/', views.item_toggle_activo, name='item_toggle_activo'),

    # Inventario - Ubicaciones
    path('ubicaciones/', views.ubicacion_lista, name='ubicacion_lista'),
    path('ubicaciones/nueva/', views.ubicacion_crear, name='ubicacion_crear'),
    path('ubicaciones/<int:pk>/editar/', views.ubicacion_editar, name='ubicacion_editar'),

    # Movimientos
    path('movimientos/', views.movimiento_lista, name='movimiento_lista'),
    path('movimientos/entrada/', views.movimiento_entrada, name='movimiento_entrada'),
    path('movimientos/salida/', views.movimiento_salida, name='movimiento_salida'),
    path('movimientos/transferencia/', views.movimiento_transferencia, name='movimiento_transferencia'),

    # Conteos
    path('conteos/', views.conteo_lista, name='conteo_lista'),
    path('conteos/nuevo/', views.conteo_nuevo, name='conteo_nuevo'),
    path('conteos/<int:pk>/', views.conteo_detalle, name='conteo_detalle'),
    path('conteos/<int:pk>/ajustar/', views.conteo_ajustar, name='conteo_ajustar'),

    # Máquinas
    path('maquinas/', views.maquina_lista, name='maquina_lista'),
    path('maquinas/nueva/', views.maquina_crear, name='maquina_crear'),
    path('maquinas/<int:pk>/editar/', views.maquina_editar, name='maquina_editar'),
    path('maquinas/<int:pk>/toggle/', views.maquina_toggle_activo, name='maquina_toggle_activo'),

    # Clientes
    path('clientes/', views.cliente_lista, name='cliente_lista'),
    path('clientes/nuevo/', views.cliente_crear, name='cliente_crear'),
    path('clientes/<int:pk>/editar/', views.cliente_editar, name='cliente_editar'),
    path('clientes/<int:pk>/toggle/', views.cliente_toggle_activo, name='cliente_toggle_activo'),

    # Reportes
    path('reportes/stock-bajo/', views.reporte_stock_bajo, name='reporte_stock_bajo'),
    path('reportes/produccion/', views.reporte_produccion, name='reporte_produccion'),

    # API
    path('api/item/<int:pk>/info/', views.api_item_info, name='api_item_info'),
    path('api/categoria/nueva/', views.api_categoria_nueva, name='api_categoria_nueva'),
]
