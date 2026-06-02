#!/usr/bin/env python
"""
Genera los íconos PWA para Transformadora de Empaques.

Uso (desde la raíz del proyecto):
    python create_icons.py

Requiere Pillow:
    pip install Pillow
"""
import os
from PIL import Image

BASE_DIR  = os.path.dirname(__file__)
SRC_ICON  = os.path.join(BASE_DIR, 'static', 'images', 'logo-icon.png')
OUT_DIR   = os.path.join(BASE_DIR, 'static', 'icons')

SPECS = [
    ('icon-512.png',         512),
    ('icon-192.png',         192),
    ('apple-touch-icon-120.png', 120),
    ('apple-touch-icon-152.png', 152),
    ('apple-touch-icon-167.png', 167),
    ('apple-touch-icon.png', 180),
]

# Fondo blanco (para contextos que no soportan transparencia)
BG_COLOR = (255, 255, 255)


def make_icon(src: Image.Image, size: int) -> Image.Image:
    """Redimensiona el logo-icon a size×size sobre fondo blanco."""
    # Padding: 10 % a cada lado para que no quede pegado al borde
    pad  = int(size * 0.10)
    inner = size - pad * 2

    # Redimensionar manteniendo proporción
    src_copy = src.copy()
    src_copy.thumbnail((inner, inner), Image.LANCZOS)

    # Canvas blanco
    canvas = Image.new('RGBA', (size, size), (*BG_COLOR, 255))

    # Centrar
    offset_x = (size - src_copy.width)  // 2
    offset_y = (size - src_copy.height) // 2

    if src_copy.mode == 'RGBA':
        canvas.paste(src_copy, (offset_x, offset_y), src_copy)
    else:
        canvas.paste(src_copy, (offset_x, offset_y))

    return canvas


def main():
    if not os.path.exists(SRC_ICON):
        print(f'ERROR: no se encontró {SRC_ICON}')
        print('Asegurate de que static/images/logo-icon.png existe.')
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    src = Image.open(SRC_ICON).convert('RGBA')

    print('Generando íconos PWA desde logo-icon.png…\n')

    for filename, size in SPECS:
        icon = make_icon(src, size)
        out_path = os.path.join(OUT_DIR, filename)
        icon.convert('RGB').save(out_path, 'PNG', optimize=True)
        print(f'  ✓  {out_path}  ({size}×{size}px)')

    print('\n¡Listo! Archivos en static/icons/')
    print('Reconstruí Docker para incluirlos:')
    print('  docker-compose down && docker-compose up --build')


if __name__ == '__main__':
    main()
