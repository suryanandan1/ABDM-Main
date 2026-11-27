"""OCR engines: OCR.space when OCR_SPACE_API_KEY is set, otherwise Mistral OCR."""
import base64

import httpx

from app.ai import AIError, client, provider_errors
from app.config import settings


OCR_SPACE_FILETYPES = {"application/pdf": "PDF", "image/png": "PNG", "image/jpeg": "JPG", "image/gif": "GIF"}


def ocr_space(data: bytes, content_type: str) -> str:
    """Read the text of a PDF or image with OCR.space (https://ocr.space/ocrapi)."""
    filetype = OCR_SPACE_FILETYPES.get(content_type)
    if filetype is None:
        raise AIError(f"OCR.space cannot read {content_type} files; upload a PDF, PNG, JPG or GIF")
    try:
        response = httpx.post(
            settings.ocr_space_url, headers={"apikey": settings.ocr_space_api_key}, timeout=180,
            files={"file": (f"document.{filetype.lower()}", data, content_type)},
            data={"language": "auto" if settings.ocr_space_engine >= 2 else "eng", "OCREngine": str(settings.ocr_space_engine),
                  "filetype": filetype, "detectOrientation": "true", "scale": "true", "isTable": "true"})
    except httpx.RequestError as exc:
        raise AIError("Could not reach OCR.space") from exc
    if response.status_code in (401, 403):
        raise AIError("OCR.space API key is invalid (check OCR_SPACE_API_KEY)")
    try:
        result = response.json()
    except ValueError:  # OCR.space answers some errors (e.g. rate limit) with plain text
        raise AIError(f"OCR.space error {response.status_code}: {response.text[:200]}") from None
    if not isinstance(result, dict):
        raise AIError(f"OCR.space error: {str(result)[:200]}")
    pages = result.get("ParsedResults") or []
    text = "\n\n".join((p.get("ParsedText") or "").strip() for p in pages if p.get("FileParseExitCode") == 1).strip()
    if result.get("IsErroredOnProcessing") and not text:
        message = result.get("ErrorMessage")
        message = "; ".join(message) if isinstance(message, list) else message
        raise AIError(f"OCR.space could not read the document: {message or 'unknown error'}")
    return text


def ocr(data: bytes, content_type: str) -> str:
    if settings.ocr_space_api_key:
        return ocr_space(data, content_type)
    uri = f"data:{content_type};base64,{base64.standard_b64encode(data).decode()}"
    document = ({"type": "document_url", "document_url": uri} if content_type == "application/pdf"
                else {"type": "image_url", "image_url": uri})
    with provider_errors():
        response = client().ocr.process(model=settings.ai_ocr_model, document=document)
    return "\n\n".join(page.markdown for page in response.pages if page.markdown).strip()
