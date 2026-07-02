"""qr — generación de códigos QR como PNG. Aísla la librería `qrcode`."""
import io

import qrcode


def qr_png_bytes(data):
    """Devuelve los bytes PNG de un código QR que codifica `data`."""
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()
