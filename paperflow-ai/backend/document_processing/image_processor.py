"""Image processor for PaperFlow AI Stage 12.

Processes raster images (JPG, JPEG, PNG, WEBP) and HEIC/HEIF images.
Normalizes, validates, and runs OCR to extract text.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from document_processing.ocr import OCRError, extract_text_from_image

logger = logging.getLogger("paperflow.image_processor")

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
    _PILLOW_AVAILABLE = True
except ImportError:
    _PILLOW_AVAILABLE = False
    UnidentifiedImageError = Exception  # type: ignore

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    _HEIF_AVAILABLE = True
except ImportError:
    _HEIF_AVAILABLE = False


class ImageProcessingError(Exception):
    """Base exception for image processing errors."""


class CorruptImageError(ImageProcessingError):
    """Raised when the image data is malformed or corrupted."""


class EmptyImageError(ImageProcessingError):
    """Raised when the image bytes are empty."""


class UnsupportedImageFormatError(ImageProcessingError):
    """Raised when the image format is not supported."""


def is_heif_supported() -> bool:
    """Check if HEIC/HEIF decoding is available."""
    return _HEIF_AVAILABLE


def process_image(
    image_bytes: bytes,
    filename: str = "image.png",
) -> dict[str, Any]:
    """Validate, inspect, and extract text from an image.

    Args:
        image_bytes: Raw binary bytes of the image.
        filename: Original file name for logging and extension hints.

    Returns:
        dict containing:
            - text: Extracted OCR text (str)
            - metadata: dict with width, height, format, mode, is_heif
            - pages: list containing 1 page item [{"page": 1, "text": "..."}]

    Raises:
        EmptyImageError: If image_bytes is empty.
        CorruptImageError: If image data cannot be decoded or verified.
        OCRError: If OCR extraction fails.
    """
    if not image_bytes or len(image_bytes) == 0:
        raise EmptyImageError(f"Image '{filename}' is empty (0 bytes).")

    if not _PILLOW_AVAILABLE:
        raise ImageProcessingError("Pillow is required for image processing.")

    # Check for HEIF without pillow-heif
    ext = (filename.split(".")[-1] or "").lower()
    if ext in ("heic", "heif") and not _HEIF_AVAILABLE:
        raise UnsupportedImageFormatError(
            f"HEIC/HEIF decoding is not available. Install pillow-heif to process {filename}."
        )

    try:
        # Load and verify image
        img_buffer = io.BytesIO(image_bytes)
        with Image.open(img_buffer) as img:
            # Check basic properties
            img_format = img.format or ext.upper()
            width, height = img.size
            mode = img.mode

            # Correct orientation if EXIF orientation tag exists
            try:
                img = ImageOps.exif_transpose(img) or img
            except Exception:
                pass

            # Perform OCR extraction
            text = extract_text_from_image(img)

            metadata = {
                "width": width,
                "height": height,
                "format": img_format,
                "mode": mode,
                "is_heif": ext in ("heic", "heif"),
                "has_text": bool(text.strip()),
                "char_count": len(text.strip()),
            }

            return {
                "text": text,
                "metadata": metadata,
                "pages": [{"page": 1, "text": text}],
            }
    except (UnidentifiedImageError, OSError) as exc:
        logger.warning("Failed to parse image '%s': %s", filename, exc)
        raise CorruptImageError(f"Image file '{filename}' is corrupted or unreadable: {exc}") from exc
    except OCRError:
        raise
    except Exception as exc:
        logger.warning("Unexpected error processing image '%s': %s", filename, exc)
        raise ImageProcessingError(f"Error processing image '{filename}': {exc}") from exc
