"""PDF validation and page-by-page text extraction with PyMuPDF."""
from pathlib import Path

import pymupdf

from app.models import PageText

PDF_MAGIC = b"%PDF-"
MIN_TEXT_CHARS = 25  # below this, a page with images is treated as scanned


class ExtractionError(ValueError):
    """Raised when a PDF cannot be read; message is safe to show to users."""


def looks_like_pdf(head: bytes) -> bool:
    return head.lstrip()[:5] == PDF_MAGIC


def extract_pages(path: Path, max_pages: int = 300) -> list[PageText]:
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # PyMuPDF raises several types for corrupt input
        raise ExtractionError("The file could not be opened as a PDF (it may be corrupt).") from exc
    with doc:
        if doc.needs_pass:
            raise ExtractionError("The PDF is password-protected. Remove the password and upload again.")
        if doc.page_count == 0:
            raise ExtractionError("The PDF has no pages.")
        if doc.page_count > max_pages:
            raise ExtractionError(f"The PDF has {doc.page_count} pages; the limit is {max_pages}.")
        pages = []
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text", sort=True) or ""
            text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
            needs_ocr = len(text) < MIN_TEXT_CHARS and bool(page.get_images(full=False))
            pages.append(PageText(page_no=i, text=text, needs_ocr=needs_ocr))
        return pages
