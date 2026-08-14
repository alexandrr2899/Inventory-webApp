from django.urls import path

from . import views


app_name = 'jaime_api'

urlpatterns = [
    path('clientes/buscar/', views.buscar_clientes, name='buscar_clientes'),
    path('clientes/<int:cliente_id>/saldo/', views.saldo_cliente, name='saldo_cliente'),
    path('facturas/pendientes/', views.facturas_pendientes, name='facturas_pendientes'),
    path('facturas/vencidas/', views.facturas_vencidas, name='facturas_vencidas'),
    path('inventario/', views.consultar_inventario, name='consultar_inventario'),
]
