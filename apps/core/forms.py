import os

from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User, Group
from decimal import Decimal
from .models import (
    Item, Categoria, Ubicacion, Stock, Maquina, Cliente,
    MovimientoInventario, Conteo, ConteoDetalle,
    DocumentoFactura, TarifaCliente, MetodoPago, CategoriaProducto,
)

# Límites de subida de archivos (MB).
MAX_PDF_MB = 25
MAX_COMPROBANTE_MB = 10
MAX_EXCEL_MB = 10


def validar_upload(archivo, *, extensiones, max_mb, magic=None):
    """Valida un archivo subido por extensión, tamaño y (opcional) bytes iniciales.

    `extensiones`: lista de extensiones permitidas en minúsculas, con punto ('.pdf').
    `magic`: si se da, los primeros bytes del archivo deben coincidir (p. ej. b'%PDF').
    Devuelve el archivo (o None si venía vacío) para usarse desde un `clean_<campo>`.
    """
    if not archivo:
        return archivo
    ext = os.path.splitext(archivo.name)[1].lower()
    if ext not in extensiones:
        raise ValidationError(
            'Tipo de archivo no permitido. Debe ser: %s.' % ', '.join(extensiones))
    if archivo.size > max_mb * 1024 * 1024:
        raise ValidationError('El archivo supera el tamaño máximo de %d MB.' % max_mb)
    if magic:
        cabecera = archivo.read(len(magic))
        archivo.seek(0)
        if cabecera != magic:
            raise ValidationError('El archivo está dañado o no es del tipo esperado.')
    return archivo


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['codigo', 'nombre', 'descripcion', 'tipo', 'categoria',
                  'unidad_medida', 'stock_minimo', 'activo']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: BOLSA-001'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'unidad_medida': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: unidad, kg, m'}),
            'stock_minimo': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
        }


class UbicacionForm(forms.ModelForm):
    class Meta:
        model = Ubicacion
        fields = ['nombre', 'tipo', 'descripcion']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class MaquinaForm(forms.ModelForm):
    class Meta:
        model = Maquina
        fields = ['codigo', 'nombre', 'area', 'descripcion', 'activo']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'area': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ['nombre', 'telefono', 'rtn', 'direccion', 'dias_credito', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: +504 9999-9999'}),
            'rtn': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'dias_credito': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': '0 = contado'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ClienteInlineForm(forms.ModelForm):
    dias_credito = forms.IntegerField(
        required=False,
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': '0 = contado'}),
    )

    class Meta:
        model = Cliente
        fields = ['nombre', 'telefono', 'rtn', 'direccion', 'dias_credito']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: +504 9999-9999'}),
            'rtn': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_dias_credito(self):
        return self.cleaned_data.get('dias_credito') or 0

    def clean_nombre(self):
        return self.cleaned_data['nombre'].strip()


class MovimientoEntradaForm(forms.Form):
    item = forms.ModelChoiceField(
        queryset=Item.objects.filter(activo=True).order_by('orden', 'nombre'),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_item'}),
        label='Ítem',
        empty_label='-- Seleccionar ítem --'
    )
    cantidad = forms.DecimalField(
        max_digits=12, decimal_places=0, min_value=Decimal('1'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'step': '1', 'min': '1',
            'inputmode': 'numeric', 'placeholder': '0',
        }),
    )
    ubicacion_destino = forms.ModelChoiceField(
        queryset=Ubicacion.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Ubicación de entrada',
        empty_label='-- Seleccionar ubicación --'
    )
    motivo = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Descripción del movimiento...'}),
    )


class MovimientoSalidaForm(forms.Form):
    item = forms.ModelChoiceField(
        queryset=Item.objects.filter(activo=True).order_by('orden', 'nombre'),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_item_salida'}),
        label='Ítem',
        empty_label='-- Seleccionar ítem --'
    )
    cantidad = forms.DecimalField(
        max_digits=12, decimal_places=0, min_value=Decimal('1'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'step': '1', 'min': '1',
            'inputmode': 'numeric', 'placeholder': '0',
        }),
    )
    ubicacion_origen = forms.ModelChoiceField(
        queryset=Ubicacion.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_ubicacion_origen'}),
        label='Ubicación de salida',
        empty_label='-- Seleccionar ubicación --'
    )
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.filter(activo=True).order_by('nombre'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='-- Sin cliente --'
    )
    maquina = forms.ModelChoiceField(
        queryset=Maquina.objects.filter(activo=True).order_by('nombre'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Máquina',
        empty_label='-- Sin máquina --'
    )
    motivo = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Descripción...'}),
    )

    def clean(self):
        cleaned = super().clean()
        item = cleaned.get('item')
        cantidad = cleaned.get('cantidad')
        ubicacion_origen = cleaned.get('ubicacion_origen')
        cliente = cleaned.get('cliente')
        maquina = cleaned.get('maquina')

        if item and item.tipo == 'producto' and not cliente:
            self.add_error('cliente', 'Para productos terminados debe seleccionar un cliente.')

        if item and item.tipo == 'repuesto' and not maquina:
            self.add_error('maquina', 'Para repuestos debe seleccionar una máquina.')

        if item and cantidad and ubicacion_origen:
            try:
                stock = Stock.objects.get(item=item, ubicacion=ubicacion_origen)
                if stock.cantidad_actual < cantidad:
                    raise ValidationError(
                        f'Stock insuficiente. Disponible: {stock.cantidad_actual} {item.unidad_medida}'
                    )
            except Stock.DoesNotExist:
                raise ValidationError(
                    f'No hay stock de "{item.nombre}" en la ubicación seleccionada.'
                )

        return cleaned


class MovimientoTransferenciaForm(forms.Form):
    item = forms.ModelChoiceField(
        queryset=Item.objects.filter(activo=True).order_by('orden', 'nombre'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Ítem',
        empty_label='-- Seleccionar ítem --'
    )
    cantidad = forms.DecimalField(
        max_digits=12, decimal_places=0, min_value=Decimal('1'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'step': '1', 'min': '1',
            'inputmode': 'numeric', 'placeholder': '0',
        }),
    )
    ubicacion_origen = forms.ModelChoiceField(
        queryset=Ubicacion.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Ubicación origen',
        empty_label='-- Seleccionar origen --'
    )
    ubicacion_destino = forms.ModelChoiceField(
        queryset=Ubicacion.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Ubicación destino',
        empty_label='-- Seleccionar destino --'
    )
    motivo = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def clean(self):
        cleaned = super().clean()
        origen = cleaned.get('ubicacion_origen')
        destino = cleaned.get('ubicacion_destino')
        item = cleaned.get('item')
        cantidad = cleaned.get('cantidad')

        if origen and destino and origen == destino:
            raise ValidationError('El origen y destino no pueden ser iguales.')

        if item and cantidad and origen:
            try:
                stock = Stock.objects.get(item=item, ubicacion=origen)
                if stock.cantidad_actual < cantidad:
                    raise ValidationError(
                        f'Stock insuficiente en origen. Disponible: {stock.cantidad_actual}'
                    )
            except Stock.DoesNotExist:
                raise ValidationError(f'No hay stock de "{item.nombre}" en la ubicación origen.')

        return cleaned


class ConteoForm(forms.ModelForm):
    fecha_hora_conteo = forms.DateTimeField(
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(
            attrs={'class': 'form-control', 'type': 'datetime-local'},
            format='%Y-%m-%dT%H:%M',
        ),
        label='Fecha y hora del conteo',
    )

    class Meta:
        model = Conteo
        fields = ['fecha', 'turno', 'tipo_conteo', 'fecha_hora_conteo', 'observaciones']
        widgets = {
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'turno': forms.Select(attrs={'class': 'form-select'}),
            'tipo_conteo': forms.HiddenInput(),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'Observaciones opcionales...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.fecha_hora_conteo:
            from django.utils import timezone as tz
            self.initial['fecha_hora_conteo'] = tz.localtime(
                self.instance.fecha_hora_conteo
            ).strftime('%Y-%m-%dT%H:%M')


class ProduccionForm(forms.Form):
    item = forms.ModelChoiceField(
        queryset=Item.objects.filter(activo=True, tipo='producto').order_by('orden', 'nombre'),
        widget=forms.Select(attrs={'class': 'form-select form-select-lg'}),
        label='Producto',
        empty_label='-- Seleccionar producto --',
    )
    cantidad = forms.DecimalField(
        max_digits=12, decimal_places=0, min_value=Decimal('1'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-lg',
            'step': '1', 'min': '1', 'placeholder': '0',
            'inputmode': 'numeric',
        }),
        label='Cantidad producida',
    )
    ubicacion_destino = forms.ModelChoiceField(
        queryset=Ubicacion.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select form-select-lg'}),
        label='Destino en bodega',
        empty_label='-- Seleccionar ubicación --',
    )
    fecha_movimiento = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={'class': 'form-control form-control-lg', 'type': 'datetime-local'},
            format='%Y-%m-%dT%H:%M',
        ),
        label='Fecha y hora de producción',
        input_formats=['%Y-%m-%dT%H:%M'],
    )
    motivo = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'rows': 2,
            'placeholder': 'Observaciones opcionales...',
        }),
        label='Observaciones',
    )


GRUPOS_CHOICES = [
    ('', '-- Sin grupo --'),
    ('Administrador', 'Administrador'),
    ('Supervisor', 'Supervisor'),
    ('Operador', 'Operador'),
]


class UsuarioCrearForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'nombre.usuario'}),
        label='Usuario',
    )
    first_name = forms.CharField(
        max_length=150, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre'}),
        label='Nombre',
    )
    last_name = forms.CharField(
        max_length=150, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apellido'}),
        label='Apellido',
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'correo@empresa.com'}),
        label='Correo',
    )
    grupo = forms.ChoiceField(
        choices=GRUPOS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Rol',
        required=False,
    )
    password = forms.CharField(
        min_length=6,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Mínimo 6 caracteres'}),
        label='Contraseña',
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Repetir contraseña'}),
        label='Confirmar contraseña',
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username=username).exists():
            raise ValidationError('Ya existe un usuario con ese nombre.')
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Las contraseñas no coinciden.')
        return cleaned


class UsuarioEditarForm(forms.Form):
    first_name = forms.CharField(
        max_length=150, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='Nombre',
    )
    last_name = forms.CharField(
        max_length=150, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='Apellido',
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
        label='Correo',
    )
    grupo = forms.ChoiceField(
        choices=GRUPOS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Rol',
        required=False,
    )
    is_active = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Usuario activo',
    )
    nueva_password = forms.CharField(
        min_length=6, required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Dejar vacío para no cambiar'}),
        label='Nueva contraseña',
    )
    nueva_password2 = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Repetir nueva contraseña'}),
        label='Confirmar nueva contraseña',
    )

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('nueva_password')
        p2 = cleaned.get('nueva_password2')
        if p1 and p2 and p1 != p2:
            self.add_error('nueva_password2', 'Las contraseñas no coinciden.')
        if p1 and not p2:
            self.add_error('nueva_password2', 'Confirma la nueva contraseña.')
        return cleaned


class ImportarItemsForm(forms.Form):
    archivo = forms.FileField(
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.xlsx,.xls'}),
        label='Archivo Excel (.xlsx)',
        help_text='Descargá la plantilla para ver el formato esperado.',
    )

    def clean_archivo(self):
        return validar_upload(self.cleaned_data.get('archivo'),
                              extensiones=['.xlsx', '.xls'], max_mb=MAX_EXCEL_MB)


class FiltroMovimientosForm(forms.Form):
    fecha_inicio = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Desde'
    )
    fecha_fin = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Hasta'
    )
    tipo_movimiento = forms.ChoiceField(
        choices=[('', 'Todos')] + MovimientoInventario.TIPO_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Tipo'
    )
    item = forms.ModelChoiceField(
        queryset=Item.objects.filter(activo=True).order_by('orden', 'nombre'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Ítem',
        empty_label='Todos los ítems'
    )


class DocumentoUploadForm(forms.Form):
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.filter(activo=True).order_by('nombre'),
        widget=forms.Select(attrs={'class': 'form-select cliente-select'}),
    )
    tipo_documento = forms.ChoiceField(
        choices=[('', 'Auto-detectar por nombre')] + list(DocumentoFactura.TIPO_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    categoria = forms.ModelChoiceField(
        queryset=CategoriaProducto.objects.filter(activa=True),
        required=False,
        empty_label='Auto-detectar por nombre',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    archivo_pdf = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'application/pdf'}),
    )

    def clean_archivo_pdf(self):
        return validar_upload(self.cleaned_data.get('archivo_pdf'),
                              extensiones=['.pdf'], max_mb=MAX_PDF_MB, magic=b'%PDF')


class DocumentoEditarForm(forms.ModelForm):
    class Meta:
        model = DocumentoFactura
        fields = [
            'cliente', 'tipo_documento', 'numero_documento', 'fecha_documento',
            'fecha_vencimiento', 'categoria', 'total_libras', 'precio_por_libra',
            'subtotal', 'isv', 'monto_total', 'estado_revision', 'notas', 'subcliente',
        ]
        widgets = {
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'tipo_documento': forms.Select(attrs={'class': 'form-select'}),
            'numero_documento': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha_documento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'fecha_vencimiento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'total_libras': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'precio_por_libra': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'subtotal': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'isv': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'monto_total': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'estado_revision': forms.Select(attrs={'class': 'form-select'}),
            'notas': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'subcliente': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].queryset = CategoriaProducto.objects.filter(activa=True)
        self.fields['categoria'].required = False


class PagoFacturaForm(forms.Form):
    fecha_pago = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'))
    metodo_pago = forms.ModelChoiceField(
        queryset=MetodoPago.objects.filter(activo=True),
        widget=forms.Select(attrs={'class': 'form-select'}))
    monto = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}))
    referencia = forms.CharField(
        required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    comprobante = forms.FileField(
        required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))
    notas = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))

    def clean_comprobante(self):
        return validar_upload(self.cleaned_data.get('comprobante'),
                              extensiones=['.pdf', '.jpg', '.jpeg', '.png', '.webp'],
                              max_mb=MAX_COMPROBANTE_MB)


class AbonoClienteForm(forms.Form):
    fecha_pago = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'))
    metodo_pago = forms.ModelChoiceField(
        queryset=MetodoPago.objects.filter(activo=True),
        widget=forms.Select(attrs={'class': 'form-select'}))
    monto = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}))
    referencia = forms.CharField(
        required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    comprobante = forms.FileField(
        required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))
    notas = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))

    def clean_comprobante(self):
        return validar_upload(self.cleaned_data.get('comprobante'),
                              extensiones=['.pdf', '.jpg', '.jpeg', '.png', '.webp'],
                              max_mb=MAX_COMPROBANTE_MB)


class MetodoPagoForm(forms.ModelForm):
    class Meta:
        model = MetodoPago
        fields = ['nombre', 'tipo', 'activo', 'orden']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'orden': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class CategoriaProductoForm(forms.ModelForm):
    class Meta:
        model = CategoriaProducto
        fields = ['nombre', 'palabra_clave', 'es_predeterminada', 'activa', 'orden', 'color']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'palabra_clave': forms.TextInput(attrs={'class': 'form-control'}),
            'es_predeterminada': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'orden': forms.NumberInput(attrs={'class': 'form-control'}),
            'color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
        }


class TarifaClienteForm(forms.ModelForm):
    class Meta:
        model = TarifaCliente
        fields = ['categoria', 'precio_por_libra', 'activa', 'fecha_inicio', 'fecha_fin', 'notas']
        widgets = {
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'precio_por_libra': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'fecha_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'fecha_fin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'notas': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].queryset = CategoriaProducto.objects.filter(activa=True)
        self.fields['categoria'].required = True
