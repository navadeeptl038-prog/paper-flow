"""OCR (Optical Character Recognition) module for PaperFlow AI Stage 12.

Handles text extraction from images and scanned documents via Tesseract OCR (pytesseract).
Detects system dependencies and provides graceful error reporting when OCR dependencies are missing.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
from typing import Any, Callable

logger = logging.getLogger("paperflow.ocr")

try:
    from PIL import Image
    _PILLOW_AVAILABLE = True
except ImportError:
    _PILLOW_AVAILABLE = False

try:
    import pytesseract
    _PYTESSERACT_AVAILABLE = True
except ImportError:
    _PYTESSERACT_AVAILABLE = False

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    _PILLOW_HEIF_AVAILABLE = True
except ImportError:
    _PILLOW_HEIF_AVAILABLE = False


class OCRError(Exception):
    """Raised when an OCR operation fails or the OCR engine is unavailable."""


# Optional hook for testing environments without Tesseract binary
_test_ocr_handler: Callable[[Any], str] | None = None


def set_test_ocr_handler(handler: Callable[[Any], str] | None) -> None:
    """Set or clear a custom OCR handler (used primarily for automated test fixtures)."""
    global _test_ocr_handler
    _test_ocr_handler = handler


def find_tesseract_binary() -> str | None:
    """Locate the tesseract executable on PATH or in standard system locations."""
    # 1. Custom env var override
    custom_cmd = (os.getenv("TESSERACT_CMD") or "").strip()
    if custom_cmd and os.path.exists(custom_cmd):
        return custom_cmd

    # 2. PATH search
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path

    # 3. Common Windows locations
    standard_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        os.path.expanduser(r"~\AppData\Local\Tesseract-OCR\tesseract.exe"),
        # Linux / Docker paths
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
    ]
    for path in standard_paths:
        if os.path.exists(path):
            return path

    return None


def get_ocr_dependencies_status() -> dict[str, Any]:
    """Report the availability of OCR engines and image processing libraries."""
    tess_path = find_tesseract_binary()
    tess_version: str | None = None

    if _PYTESSERACT_AVAILABLE and tess_path:
        try:
            pytesseract.pytesseract.tesseract_cmd = tess_path
            tess_version = str(pytesseract.get_tesseract_version())
        except Exception:
            tess_version = None

    return {
        "pytesseract_available": _PYTESSERACT_AVAILABLE,
        "pillow_available": _PILLOW_AVAILABLE,
        "pillow_heif_available": _PILLOW_HEIF_AVAILABLE,
        "tesseract_installed": tess_path is not None,
        "tesseract_path": tess_path,
        "tesseract_version": tess_version,
    }


def is_ocr_available() -> bool:
    """Return True if Tesseract OCR is ready to extract text."""
    if _test_ocr_handler is not None:
        return True
    return bool(_PYTESSERACT_AVAILABLE and find_tesseract_binary())


def extract_text_from_image(image_input: Any) -> str:
    """Extract text from an image (PIL.Image or raw bytes) using Tesseract OCR.

    Args:
        image_input: PIL Image instance or raw bytes.

    Returns:
        Extracted text string.

    Raises:
        OCRError: If OCR engine is unavailable or extraction fails.
    """
    if _test_ocr_handler is not None:
        return _test_ocr_handler(image_input)

    if not _PILLOW_AVAILABLE:
        raise OCRError("Pillow is not installed. Cannot process image for OCR.")

    # Convert bytes to PIL Image if necessary
    pil_image: Image.Image
    if isinstance(image_input, (bytes, bytearray)):
        if len(image_input) == 0:
            raise OCRError("Image data is empty (0 bytes).")
        try:
            pil_image = Image.open(io.BytesIO(image_input))
        except Exception as exc:
            raise OCRError(f"Failed to decode image data: {exc}") from exc
    elif hasattr(image_input, "convert"):
        pil_image = image_input
    else:
        raise OCRError(f"Unsupported image input type: {type(image_input)}")

    if not _PYTESSERACT_AVAILABLE:
        raise OCRError(
            "pytesseract is not installed. Install with `pip install pytesseract`."
        )

    tess_binary = find_tesseract_binary()
    if not tess_binary:
        raise OCRError(
            "Tesseract OCR binary not found on system. "
            "Please install Tesseract OCR (e.g. `apt-get install tesseract-ocr` or download for Windows)."
        )

    try:
        pytesseract.pytesseract.tesseract_cmd = tess_binary
        # Ensure image is in RGB or Grayscale mode
        if pil_image.mode not in ("RGB", "L"):
            pil_image = pil_image.convert("RGB")

        text = pytesseract.image_to_string(pil_image)
        return text.strip()
    except Exception as exc:
        logger.warning("pytesseract execution failed: %s", exc)
        raise OCRError(f"OCR processing failed: {exc}") from exc
