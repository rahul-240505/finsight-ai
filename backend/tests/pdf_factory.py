"""Build small text PDFs in memory (Helvetica, one text object per page), for tests and the
evaluation corpus. Paragraphs are separated by blank lines and wrapped at ~95 characters."""

import textwrap

LINES_PER_PAGE = 50


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _content(text: str) -> bytes:
    ops = ["BT", "/F1 10 Tf", "14 TL", "60 760 Td"]
    lines: list[str] = []
    for paragraph in text.split("\n\n"):
        lines.extend(textwrap.wrap(paragraph, 95) or [""])
        lines.append("")
    if len(lines) > LINES_PER_PAGE:
        raise ValueError(f"page text needs {len(lines)} lines; max {LINES_PER_PAGE}")
    ops += [f"({_escape(line)}) Tj T*" for line in lines]
    ops.append("ET")
    return "\n".join(ops).encode("cp1252")


def make_pdf(pages: list[str]) -> bytes:
    n = len(pages)
    page_ids = [4 + 2 * i for i in range(n)]
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    for page_id, text in zip(page_ids, pages, strict=True):
        stream = _content(text)
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>"
        ).encode()
        objects[page_id + 1] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for number in range(1, size):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
