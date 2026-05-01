from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal
from .models import (
    Item, Categoria, Ubicacion, Stock, Maquina, Cliente,
    MovimientoInventario, Conteo, ConteoDetalle
)


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
        fields = ['nombre', 'telefono', 'rtn', 'direccion', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: +504 9999-9999'}),
            'rtn': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class MovimientoEntradaForm(forms.Form):
    item = forms.ModelChoiceField(
        queryset=Item.objects.filter(activo=True).order_by('nombre'),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_item'}),
        label='Ítem',
        empty_label='-- Seleccionar ítem --'
    )
    cantidad = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0'}),
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
        queryset=Item.objects.filter(activo=True).order_by('nombre'),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_item_salida'}),
        label='Ítem',
        empty_label='-- Seleccionar ítem --'
    )
    cantidad = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0'}),
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
        queryset=Item.objects.filter(activo=True).order_by('nombre'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Ítem',
        empty_label='-- Seleccionar ítem --'
    )
    cantidad = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0'}),
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
    class Meta:
        model = Conteo
        fields = ['fecha', 'turno', 'observaciones']
        widgets = {
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'turno': forms.Select(attrs={'class': 'form-select'}),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Observaciones opcionales...'}),
        }


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
        queryset=Item.objects.filter(activo=True).order_by('nombre'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Ítem',
        empty_label='Todos los ítems'
    )
