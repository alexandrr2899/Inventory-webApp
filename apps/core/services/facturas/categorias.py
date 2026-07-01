"""categorias — siembra inicial de CategoriaProducto y mapeo de los strings viejos.

Recibe las clases como argumentos para usarse desde una data migration
(modelos históricos) y desde tests (modelos reales)."""

_SIEMBRA = [
    # (nombre, palabra_clave, es_predeterminada, orden)
    ('Camiseta', 'camiseta', False, 0),
    ('Lisa', 'lisa', True, 1),
    ('Otro', '', False, 2),
]

# string viejo de producto -> nombre de categoría
_MAPA = {'camiseta': 'Camiseta', 'lisa': 'Lisa', 'otro': 'Otro'}


def sembrar_y_migrar(CategoriaProducto, DocumentoFactura, TarifaCliente):
    por_nombre = {}
    for nombre, kw, default, orden in _SIEMBRA:
        obj, _ = CategoriaProducto.objects.get_or_create(
            nombre=nombre,
            defaults={'palabra_clave': kw, 'es_predeterminada': default, 'orden': orden})
        por_nombre[nombre] = obj

    def cat_para(prod, default_nombre=None):
        nombre = _MAPA.get((prod or '').strip().lower())
        if not nombre:
            nombre = default_nombre
        return por_nombre.get(nombre) if nombre else None

    for doc in DocumentoFactura.objects.all():
        cat = cat_para(doc.producto)          # documentos sin producto quedan sin categoría
        if cat is not None:
            doc.categoria = cat
            doc.save(update_fields=['categoria'])

    for tar in TarifaCliente.objects.all():
        cat = cat_para(tar.producto, default_nombre='Otro')  # las tarifas siempre tienen producto
        tar.categoria = cat
        tar.save(update_fields=['categoria'])
