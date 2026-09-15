"""Validadores reutilizables a nivel de modelo."""
import os

from django.core.exceptions import ValidationError


def validar_comprobante_gasto(archivo):
    """Acepta PDF/JPG/PNG/WEBP de hasta 10 MB y comprueba su firma real."""
    if not archivo:
        return
    ext = os.path.splitext(archivo.name)[1].lower()
    permitidas = ('.pdf', '.jpg', '.jpeg', '.png', '.webp')
    if ext not in permitidas:
        raise ValidationError('Tipo de archivo no permitido. Debe ser PDF, JPG, PNG o WEBP.')
    if archivo.size > 10 * 1024 * 1024:
        raise ValidationError('El archivo supera el tamaño máximo de 10 MB.')
    cabecera = archivo.read(16)
    archivo.seek(0)
    firmas = {
        '.pdf': cabecera.startswith(b'%PDF'),
        '.jpg': cabecera.startswith(b'\xff\xd8\xff'),
        '.jpeg': cabecera.startswith(b'\xff\xd8\xff'),
        '.png': cabecera.startswith(b'\x89PNG\r\n\x1a\n'),
        '.webp': cabecera.startswith(b'RIFF') and cabecera[8:12] == b'WEBP',
    }
    if not firmas[ext]:
        raise ValidationError('El comprobante está dañado o no coincide con su tipo de archivo.')
