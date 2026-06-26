"""pdf_service — extracción de texto de PDFs con PyMuPDF (fitz)."""
import fitz  # PyMuPDF

from .pdf_extractors.factura_extractor import FacturaExtractor
from .pdf_extractors.envio_extractor import EnvioExtractor


def extraer_texto(archivo):
    """Devuelve el texto plano de un PDF.

    `archivo` puede ser una ruta (str/Path) o un objeto file-like con .read().
    """
    data = None
    if hasattr(archivo, 'read'):
        pos = archivo.tell() if hasattr(archivo, 'tell') else None
        data = archivo.read()
        if pos is not None and hasattr(archivo, 'seek'):
            archivo.seek(pos)
        doc = fitz.open(stream=data, filetype='pdf')
    else:
        doc = fitz.open(archivo)

    partes = []
    try:
        for pagina in doc:
            partes.append(pagina.get_text())
    finally:
        doc.close()
    return '\n'.join(partes)


def get_extractor(tipo_documento):
    """Devuelve la instancia de extractor según el tipo de documento."""
    if tipo_documento == 'envio':
        return EnvioExtractor()
    return FacturaExtractor()
