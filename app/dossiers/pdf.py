"""Render do documento original, sem a rotação própria das folhas kanban."""
from __future__ import annotations

import io
import threading
from pathlib import Path

import pypdfium2 as pdfium

from . import DossierError

PDF_LOCK = threading.RLock()  # PDFium não é seguro entre threads.
MAX_PAGES = 250
MAX_BYTES = 80 * 1024 * 1024


def inspect_pdf(path: Path) -> int:
    with PDF_LOCK:
        try:
            with pdfium.PdfDocument(path) as doc:
                count = len(doc)
                if not 1 <= count <= MAX_PAGES:
                    raise DossierError(f"O PDF deve ter entre 1 e {MAX_PAGES} páginas.")
                return count
        except DossierError:
            raise
        except Exception:
            raise DossierError("Não foi possível abrir este PDF. Confirma que é válido e não está protegido por palavra-passe.") from None


def page_data(path: Path, page_number: int, *, size=2400) -> tuple[bytes, str]:
    with PDF_LOCK:
        try:
            with pdfium.PdfDocument(path) as doc:
                if not 1 <= page_number <= len(doc):
                    raise DossierError("Página não encontrada.", 404)
                page = doc[page_number - 1]
                try:
                    textpage = page.get_textpage()
                    try:
                        text = textpage.get_text_range()[:14000]
                    finally:
                        textpage.close()
                    width, height = page.get_size()
                    if min(width, height) <= 0:
                        raise ValueError()
                    bitmap = page.render(scale=min(3.0, size / max(width, height)))
                    try:
                        out = io.BytesIO()
                        bitmap.to_pil().convert("RGB").save(out, format="PNG")
                        return out.getvalue(), text
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        except DossierError:
            raise
        except Exception:
            raise DossierError("Não foi possível ler esta página do PDF.", 422) from None
