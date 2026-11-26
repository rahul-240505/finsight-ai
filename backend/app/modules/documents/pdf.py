"""PDF text extraction with limits. Uploaded files are untrusted: check the bytes, size and
page count before doing real work, and clean the text before it reaches Postgres or a prompt.
"""

import io
import logging
import re
import unicodedata

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.core.errors import AppError

logger = logging.getLogger(__name__)

# C0/C1 control characters except tab and newline. Postgres text can't store NUL at all.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_SPACES = re.compile(r"[ \t ]+")


class InvalidPdf(AppError):
    status_code, code = 422, "invalid_pdf"
    message = "The file is not a readable PDF."


def clean_text(text: str) -> str:
    """NFKC folds ligatures (ﬁ → fi) and full-width forms; then drop control characters and
    squeeze runs of spaces, keeping line breaks."""
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL.sub(" ", text)
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def extract_pages(data: bytes, max_pages: int) -> list[str]:
    """Cleaned text of each page (index 0 = page 1). Raises InvalidPdf with a safe message."""
    if not data.startswith(b"%PDF-"):
        raise InvalidPdf("The file does not start with a PDF header.")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise InvalidPdf("Encrypted PDFs are not supported. Upload an unencrypted copy.")
        page_count = len(reader.pages)
        if page_count == 0:
            raise InvalidPdf("The PDF has no pages.")
        if page_count > max_pages:
            raise InvalidPdf(f"The PDF has {page_count} pages; the limit is {max_pages}.")
        pages = [clean_text(page.extract_text() or "") for page in reader.pages]
    except InvalidPdf:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError) as exc:
        # Malformed files raise many exception types; the details stay in our logs.
        logger.info("pdf parse failed: %s", type(exc).__name__)
        raise InvalidPdf() from exc
    if not any(pages):
        raise InvalidPdf("No text found. Scanned (image-only) PDFs are not supported.")
    return pages
