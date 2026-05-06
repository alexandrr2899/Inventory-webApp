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
    path('inventario/<int:pk>/historial/', views.item_historial, name='item_historial'),

    # Inventario - Ubicaciones
    path('ubicaciones/', views.ubicacion_lista, name='ubicacion_lista'),
    path('ubicaciones/nueva/', views.ubicacion_crear, name='ubicacion_crear'),
    path('ubicaciones/<int:pk>/editar/', views.ubicacion_editar, name='ubicacion_editar'),

    # Movimientos
    path('movimientos/', views.movimiento_lista, name='movimiento_lista'),
    path('movimientos/entrada/', views.movimiento_entrada, name='movimiento_entrada'),
    path('movimientos/salida/', views.movimiento_salida, name='movimiento_salida'),
    path('movimientos/transferencia/', views.movimiento_transferencia, name='movimiento_transferencia'),
    path('movimientos/<int:pk>/', views.movimiento_detalle, name='movimiento_detalle'),
    path('movimientos/<int:pk>/editar/', views.movimiento_editar, name='movimiento_editar'),
    path('movimientos/<int:pk>/anular/', views.movimiento_anular, name='movimiento_anular'),
    path('movimientos/<int:pk>/eliminar/', views.movimiento_eliminar, name='movimiento_eliminar'),

    # Conteos
    path('conteos/', views.conteo_lista, name='conteo_lista'),
    path('conteos/nuevo/', views.conteo_nuevo, name='conteo_nuevo'),
    path('conteos/<int:pk>/', views.conteo_detalle, name='conteo_detalle'),
    path('conteos/<int:pk>/conciliar/', views.conteo_conciliar, name='conteo_conciliar'),
    path('conteos/<int:pk>/ajustar/<int:det_pk>/', views.conteo_ajustar_detalle, name='conteo_ajustar_detalle'),
    path('conteos/<int:pk>/ajustar-todos/', views.conteo_ajustar_todos, name='conteo_ajustar_todos'),
    path('conteos/<int:pk>/conciliado/', views.conteo_marcar_conciliado, name='conteo_marcar_conciliado'),

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
    path('reportes/pigmentos/', views.reporte_consumo_pigmentos, name='reporte_consumo_pigmentos'),

    # Producción
    path('produccion/nueva/', views.produccion_nueva, name='produccion_nueva'),

    # Importar Excel
    path('importar/items/', views.importar_items, name='importar_items'),
    path('importar/plantilla/', views.descargar_plantilla, name='descargar_plantilla'),

    # Usuarios (solo staff)
    path('usuarios/', views.usuario_lista, name='usuario_lista'),
    path('usuarios/nuevo/', views.usuario_crear, name='usuario_crear'),
    path('usuarios/<int:pk>/editar/', views.usuario_editar, name='usuario_editar'),

    # API
    path('api/item/<int:pk>/info/', views.api_item_info, name='api_item_info'),
    path('api/categoria/nueva/', views.api_categoria_nueva, name='api_categoria_nueva'),
]
