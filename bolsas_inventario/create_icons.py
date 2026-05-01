#!/usr/bin/env python
"""
Genera los íconos PWA para Inventario Bolsas.

Uso (desde la raíz del proyecto):
    python create_icons.py

Requiere Pillow (ya incluido en requirements.txt):
    pip install Pillow
"""
import os
import math
from PIL import Image, ImageDraw


# ── Colores del tema ──────────────────────────────────────────────────────────
PRIMARY   = (13, 110, 253)       # Bootstrap #0d6efd
PRIMARY_D = (10,  88, 202)       # sombra/borde
WHITE     = (255, 255, 255)
BG        = (244, 246, 249)      # fondo de la app


def draw_rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill):
    x1, y1, x2, y2 = xy
    draw.ellipse([x1, y1, x1 + 2*radius, y1 + 2*radius], fill=fill)
    draw.ellipse([x2 - 2*radius, y1, x2, y1 + 2*radius], fill=fill)
    draw.ellipse([x1, y2 - 2*radius, x1 + 2*radius, y2], fill=fill)
    draw.ellipse([x2 - 2*radius, y2 - 2*radius, x2, y2], fill=fill)
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)


def make_icon(size: int) -> Image.Image:
    img  = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Fondo redondeado ─────────────────────────────────────────────────
    r = size // 5
    draw_rounded_rect(draw, [0, 0, size - 1, size - 1], r, PRIMARY)

    # Degradado suave: franja clara arriba
    overlay = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    for i in range(size // 3):
        alpha = int(40 * (1 - i / (size / 3)))
        ov_draw.rectangle([0, i, size, i + 1], fill=(255, 255, 255, alpha))
    img.alpha_composite(overlay)
    draw = ImageDraw.Draw(img)

    # ── Ícono: caja de inventario ─────────────────────────────────────────
    lw  = max(size // 22, 2)
    pad = size // 5                # margen ícono

    # Dimensiones de la caja
    bx1 = pad
    bx2 = size - pad
    by2 = size - pad
    bh  = int((by2 - bx1) * 0.55)  # alto del cuerpo
    by1 = by2 - bh

    # Cuerpo de la caja (rectángulo)
    draw.rectangle([bx1, by1, bx2, by2], outline=WHITE, width=lw)

    # Línea horizontal central (flejes)
    mid_y = by1 + bh // 2
    draw.line([bx1, mid_y, bx2, mid_y], fill=WHITE, width=lw)

    # Línea vertical central (partición)
    mid_x = (bx1 + bx2) // 2
    draw.line([mid_x, by1, mid_x, by2], fill=WHITE, width=lw)

    # Tapas abiertas de la caja
    flap   = bh // 3
    gap    = lw * 2            # separación entre tapas
    angle  = math.radians(20)  # ángulo de apertura

    # Tapa izquierda (abre hacia arriba/izquierda)
    tlx2 = mid_x - gap
    tly2 = by1
    tlx1 = bx1 + int(flap * math.sin(angle))
    tly1 = by1 - int(flap * math.cos(angle))
    draw.line([bx1, tly2, tlx1, tly1], fill=WHITE, width=lw)
    draw.line([tlx2, tly2, tlx1 + (tlx2 - bx1), tly1], fill=WHITE, width=lw)
    draw.line([tlx1, tly1, tlx1 + (tlx2 - bx1), tly1], fill=WHITE, width=lw)

    # Tapa derecha (abre hacia arriba/derecha)
    trx1 = mid_x + gap
    try2 = by1
    trx2 = bx2 - int(flap * math.sin(angle))
    try1 = by1 - int(flap * math.cos(angle))
    draw.line([bx2, try2, trx2, try1], fill=WHITE, width=lw)
    draw.line([trx1, try2, trx2 - (bx2 - trx1), try1], fill=WHITE, width=lw)
    draw.line([trx2, try1, trx2 - (bx2 - trx1), try1], fill=WHITE, width=lw)

    return img


def save_icon(img: Image.Image, path: str, size: int):
    resized = img.resize((size, size), Image.LANCZOS)
    rgb = Image.new('RGB', (size, size), PRIMARY)
    rgb.paste(resized, mask=resized.split()[3])  # composición sobre fondo sólido
    rgb.save(path, 'PNG', optimize=True)
    print(f'  ✓  {path}  ({size}×{size}px)')


def main():
    out_dir = os.path.join(os.path.dirname(__file__), 'static', 'icons')
    os.makedirs(out_dir, exist_ok=True)

    print('Generando íconos PWA…\n')

    # Generar en alta resolución y reducir con LANCZOS
    base = make_icon(1024)

    specs = [
        ('icon-512.png',         512),
        ('icon-192.png',         192),
        ('apple-touch-icon.png', 180),
    ]

    for filename, size in specs:
        save_icon(base, os.path.join(out_dir, filename), size)

    print('\n¡Listo! Archivos generados en static/icons/')
    print('Si usás Docker, reconstruí la imagen para incluirlos:')
    print('  docker-compose down && docker-compose up --build')


if __name__ == '__main__':
    main()
