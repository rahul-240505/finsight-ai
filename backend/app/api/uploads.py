"""Reading raw-body uploads (the file is the request body; no multipart library needed)."""

from fastapi import Request

from app.core.errors import PayloadTooLarge, UnsupportedMediaType


async def read_body(request: Request, allowed_types: set[str], limit: int) -> bytes:
    """Read the upload with a hard size cap, without trusting Content-Length alone."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in allowed_types:
        expected = " or ".join(sorted(allowed_types))
        raise UnsupportedMediaType(
            f"Send the file as the request body with Content-Type: {expected}."
        )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise PayloadTooLarge(f"The file is larger than {limit} bytes.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise PayloadTooLarge(f"The file is larger than {limit} bytes.")
        chunks.append(chunk)
    return b"".join(chunks)
