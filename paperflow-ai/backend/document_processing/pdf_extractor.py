"""PDF text extractor for PaperFlow AI Stage 12.

Handles digital text extraction and scanned PDF OCR using pypdf and pytesseract.
Detects encrypted PDFs, empty files, and corrupt PDF structures.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import pypdf
from pypdf.errors import EmptyFileError as PypdfEmptyFileError, PdfReadError

from document_processing.ocr import OCRError, extract_text_from_image, is_ocr_available

logger = logging.getLogger("paperflow.pdf_extractor")


class PDFExtractionError(Exception):
    """Base exception for PDF extraction issues."""


class CorruptPDFError(PDFExtractionError):
    """Raised when the PDF file structure is corrupted or invalid."""


class EncryptedPDFError(PDFExtractionError):
    """Raised when the PDF is password-protected or encrypted."""


class EmptyPDFError(PDFExtractionError):
    """Raised when the PDF is 0 bytes or has 0 pages."""


def extract_pdf_text(
    pdf_bytes: bytes,
    filename: str = "document.pdf",
    enable_ocr_for_scanned: bool = True,
) -> dict[str, Any]:
    """Extract text page-by-page from a PDF document.

    If a page contains no digital text, attempts OCR on embedded images.

    Args:
        pdf_bytes: Raw binary content of the PDF.
        filename: Document filename for error logging and metadata.
        enable_ocr_for_scanned: Whether to attempt OCR on scanned pages.

    Returns:
        dict containing:
            - text: Combined normalized text across all pages (str)
            - pages: List of dicts with page number, text, and is_scanned flag
            - metadata: PDF metadata (page_count, is_scanned, is_encrypted, etc.)

    Raises:
        EmptyPDFError: If file is 0 bytes or has no pages.
        CorruptPDFError: If PDF format is invalid or unreadable.
        EncryptedPDFError: If PDF is encrypted and cannot be read.
    """
    if not pdf_bytes or len(pdf_bytes) == 0:
        raise EmptyPDFError(f"PDF file '{filename}' is empty (0 bytes).")

    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    except (PypdfEmptyFileError, ValueError) as exc:
        raise EmptyPDFError(f"PDF file '{filename}' contains no readable data: {exc}") from exc
    except PdfReadError as exc:
        raise CorruptPDFError(f"PDF file '{filename}' is corrupted: {exc}") from exc
    except Exception as exc:
        raise CorruptPDFError(f"Failed to open PDF '{filename}': {exc}") from exc

    # Check for encryption
    if reader.is_encrypted:
        # Attempt decryption with empty password (some PDFs are technically encrypted with empty pass)
        try:
            decrypt_result = reader.decrypt("")
            if decrypt_result == pypdf.constants.PasswordType.NOT_DECRYPTED:
                raise EncryptedPDFError(f"PDF '{filename}' is encrypted and requires a password.")
        except EncryptedPDFError:
            raise
        except Exception as exc:
            raise EncryptedPDFError(f"PDF '{filename}' is encrypted: {exc}") from exc

    num_pages = len(reader.pages)
    if num_pages == 0:
        raise EmptyPDFError(f"PDF '{filename}' contains 0 pages.")

    pages_result: list[dict[str, Any]] = []
    scanned_pages_count = 0
    total_extracted_chars = 0

    for idx, page in enumerate(reader.pages, start=1):
        page_text = ""
        is_page_scanned = False

        try:
            page_text = (page.extract_text() or "").strip()
        except Exception as exc:
            logger.debug("extract_text() failed on page %d of %s: %s", idx, filename, exc)
            page_text = ""

        # If page has very little or no native text, check for scanned page
        if len(page_text) < 10 and enable_ocr_for_scanned:
            ocr_text_parts: list[str] = []
            try:
                # Extract embedded images from page
                for img_obj in page.images:
                    try:
                        img_bytes = img_obj.data
                        if img_bytes and len(img_bytes) > 0:
                            extracted_ocr = extract_text_from_image(img_bytes)
                            if extracted_ocr.strip():
                                ocr_text_parts.append(extracted_ocr.strip())
                    except OCRError:
                        # Re-raise or log OCR specific issues
                        raise
                    except Exception as img_exc:
                        logger.debug("Failed extracting image on page %d: %s", idx, img_exc)

                if ocr_text_parts:
                    page_text = "\n".join(ocr_text_parts)
                    is_page_scanned = True
                    scanned_pages_count += 1
                elif len(page.images) > 0:
                    # Has images but no OCR text extracted
                    is_page_scanned = True
                    scanned_pages_count += 1
            except OCRError:
                raise
            except Exception as ocr_exc:
                logger.warning("Scanned PDF OCR failed for page %d of %s: %s", idx, filename, ocr_exc)

        total_extracted_chars += len(page_text)
        pages_result.append({
            "page": idx,
            "text": page_text,
            "is_scanned": is_page_scanned,
        })

    # Read native PDF metadata if present
    doc_info = reader.metadata or {}
    pdf_meta = {
        "page_count": num_pages,
        "is_scanned": scanned_pages_count > 0,
        "scanned_pages_count": scanned_pages_count,
        "is_encrypted": False,
        "title": str(doc_info.get("/Title") or ""),
        "author": str(doc_info.get("/Author") or ""),
        "creator": str(doc_info.get("/Creator") or ""),
        "producer": str(doc_info.get("/Producer") or ""),
        "total_chars": total_extracted_chars,
    }

    combined_text = "\n\n".join(
        f"--- Page {p['page']} ---\n{p['text']}" if p["text"] else f"--- Page {p['page']} ---"
        for p in pages_result
    ).strip()

    return {
        "text": combined_text,
        "pages": pages_result,
        "metadata": pdf_meta,
    }
