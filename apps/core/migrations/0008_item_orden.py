from django.db import migrations, models


def _normalizar(nombre):
    """Lowercase sin tildes para comparar."""
    return (
        nombre.lower()
        .replace('á', 'a').replace('é', 'e')
        .replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
        .replace('ñ', 'n')
    )


def asignar_orden_inicial(apps, schema_editor):
    """
    Asigna orden 1-6 a los ítems tipo camiseta según tamaño y color.
    Solo actúa sobre productos con 'camiseta' en el nombre.
    Cualquier ítem no reconocido queda en orden=0 (fallback por nombre).

    Orden esperado:
      1  Bolsa Camiseta Grande
      2  Bolsa Camiseta Mediana
      3  Bolsa Camiseta Pequeña
      4  Bolsa Camiseta Grande Negra
      5  Bolsa Camiseta Mediana Negra
      6  Bolsa Camiseta Pequeña Negra
    """
    Item = apps.get_model('core', 'Item')

    reglas = [
        # (orden, requiere, excluye)
        (1, ['camiseta', 'grande'],  ['negra']),
        (2, ['camiseta', 'mediana'], ['negra']),
        (3, ['camiseta', 'peque'],   ['negra']),   # cubre "pequeña" / "pequena"
        (4, ['camiseta', 'grande',  'negra'], []),
        (5, ['camiseta', 'mediana', 'negra'], []),
        (6, ['camiseta', 'peque',   'negra'], []),
    ]

    for item in Item.objects.filter(tipo='producto'):
        n = _normalizar(item.nombre)
        asignado = False
        for orden, requiere, excluye in reglas:
            if all(r in n for r in requiere) and not any(e in n for e in excluye):
                item.orden = orden
                item.save(update_fields=['orden'])
                asignado = True
                break
        # Si no coincide ninguna regla → queda orden=0 (sin cambio)


def revertir_orden(apps, schema_editor):
    Item = apps.get_model('core', 'Item')
    Item.objects.update(orden=0)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_detallemovimiento'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='orden',
            field=models.PositiveIntegerField(
                default=0,
                verbose_name='Orden',
                help_text='Posición en listados. 0 = sin orden definido (usa nombre como fallback).',
            ),
        ),
        migrations.AlterModelOptions(
            name='item',
            options={
                'ordering': ['orden', 'nombre'],
                'verbose_name': 'Ítem',
                'verbose_name_plural': 'Ítems',
                'permissions': [
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
                ],
            },
        ),
        migrations.RunPython(asignar_orden_inicial, revertir_orden),
    ]
