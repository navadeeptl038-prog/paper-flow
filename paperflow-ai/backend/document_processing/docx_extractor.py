"""DOCX text extractor for PaperFlow AI Stage 12.

Extracts text from Microsoft Word documents (.docx) including paragraphs,
headings, lists, and tables in sequential reading order.
"""

from __future__ import annotations

import io
import logging
import zipfile
from typing import Any

logger = logging.getLogger("paperflow.docx_extractor")

try:
    import docx
    from docx.opc.exceptions import PackageNotFoundError
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False
    PackageNotFoundError = Exception  # type: ignore


class DOCXExtractionError(Exception):
    """Base exception for DOCX extraction issues."""


class CorruptDOCXError(DOCXExtractionError):
    """Raised when the DOCX file is corrupted or not a valid OPC package."""


class EmptyDOCXError(DOCXExtractionError):
    """Raised when the DOCX file is empty."""


def extract_docx_text(
    docx_bytes: bytes,
    filename: str = "document.docx",
) -> dict[str, Any]:
    """Extract full text and structure from a DOCX file.

    Args:
        docx_bytes: Raw binary content of the .docx file.
        filename: Document filename for logging and error reporting.

    Returns:
        dict containing:
            - text: Normalized full text string
            - pages: Simulated page list [{"page": 1, "text": "..."}]
            - metadata: DOCX metadata (paragraphs_count, tables_count, word_count, etc.)

    Raises:
        EmptyDOCXError: If file is 0 bytes.
        CorruptDOCXError: If file is not a valid DOCX document or corrupted.
    """
    if not docx_bytes or len(docx_bytes) == 0:
        raise EmptyDOCXError(f"DOCX file '{filename}' is empty (0 bytes).")

    if not _DOCX_AVAILABLE:
        raise DOCXExtractionError("python-docx is not installed.")

    try:
        buffer = io.BytesIO(docx_bytes)
        doc = docx.Document(buffer)
    except (zipfile.BadZipFile, PackageNotFoundError) as exc:
        raise CorruptDOCXError(f"DOCX file '{filename}' is not a valid Word document: {exc}") from exc
    except Exception as exc:
        raise CorruptDOCXError(f"Failed to read DOCX file '{filename}': {exc}") from exc

    text_parts: list[str] = []
    paragraph_count = 0
    table_count = len(doc.tables)

    # 1. Extract paragraphs
    for p in doc.paragraphs:
        p_text = p.text.strip()
        if p_text:
            text_parts.append(p_text)
            paragraph_count += 1

    # 2. Extract table content
    table_texts: list[str] = []
    for t_idx, table in enumerate(doc.tables, start=1):
        rows_text = []
        for row in table.rows:
            cell_texts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cell_texts:
                rows_text.append(" | ".join(cell_texts))
        if rows_text:
            table_texts.append("\n".join(rows_text))

    if table_texts:
        text_parts.append("\n--- Tables ---\n" + "\n\n".join(table_texts))

    full_text = "\n\n".join(text_parts).strip()
    word_count = len(full_text.split()) if full_text else 0

    metadata = {
        "paragraph_count": paragraph_count,
        "table_count": table_count,
        "word_count": word_count,
        "char_count": len(full_text),
    }

    # DOCX files do not have explicit page breaks without a rendering engine; treat as page 1
    return {
        "text": full_text,
        "pages": [{"page": 1, "text": full_text}],
        "metadata": metadata,
    }
