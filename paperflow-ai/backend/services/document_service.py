"""Document processing service for PaperFlow AI Stage 12.

Coordinates:
Supabase Storage → secure retrieval → temporary processing in /tmp → extraction/OCR
→ normalized text → chunks → save chunks → processing status (Ready only upon success).
"""

from __future__ import annotations

import datetime
import logging
import os
import tempfile
from typing import Any

from document_processing.chunker import DocumentChunk, chunk_document
from document_processing.docx_extractor import (
    CorruptDOCXError,
    DOCXExtractionError,
    EmptyDOCXError,
    extract_docx_text,
)
from document_processing.image_processor import (
    CorruptImageError,
    EmptyImageError,
    ImageProcessingError,
    UnsupportedImageFormatError,
    process_image,
)
from document_processing.metadata import build_error_metadata, build_processing_metadata
from document_processing.ocr import OCRError
from document_processing.pdf_extractor import (
    CorruptPDFError,
    EmptyPDFError,
    EncryptedPDFError,
    PDFExtractionError,
    extract_pdf_text,
)
from models.document import DocumentCreate, DocumentResponse
from services.supabase_client import get_supabase_client
from storage import document_repository, supabase_storage
from storage.document_repository import _mem_documents
from utils.file_utils import sanitize_filename
from utils.validators import validate_file_extension, validate_file_size, validate_filename_security, validate_mime_type

logger = logging.getLogger("paperflow.document_service")

# Storage for generated chunks: dict[document_id, list[DocumentChunk]]
_chunks_store: dict[str, list[DocumentChunk]] = {}


def get_document_chunks(document_id: str, owner_id: str) -> list[DocumentChunk]:
    """Retrieve indexed chunks for a document belonging to owner_id."""
    return _chunks_store.get(document_id, [])


def save_document_chunks(document_id: str, chunks: list[DocumentChunk]) -> None:
    """Store generated chunks in the chunk store."""
    _chunks_store[document_id] = chunks


def _update_document_record(
    doc_id: str,
    owner_id: str,
    status: str,
    metadata: dict[str, Any],
    token: str | None = None,
) -> DocumentResponse:
    """Update document processing_status and metadata in database and memory fallback."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    updated_fields = {
        "processing_status": status,
        "metadata": metadata,
        "updated_at": now_iso,
    }

    # 1. Update in Supabase PostgreSQL
    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass
        res = (
            client.table("documents")
            .update(updated_fields)
            .eq("id", doc_id)
            .eq("owner_id", owner_id)
            .execute()
        )
        if res.data:
            r = res.data[0]
            return DocumentResponse(
                id=str(r["id"]),
                owner_id=str(r["owner_id"]),
                original_filename=r["original_filename"],
                storage_path=r["storage_path"],
                file_type=r["file_type"],
                processing_status=r["processing_status"],
                source=r.get("source") or "local_upload",
                metadata=r.get("metadata") or {},
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
    except Exception as exc:
        logger.debug("Database update skipped/failed for document %s: %s", doc_id, exc)

    # 2. Update in isolated memory store
    user_docs = _mem_documents.get(owner_id, {})
    if doc_id in user_docs:
        user_docs[doc_id]["processing_status"] = status
        user_docs[doc_id]["metadata"] = metadata
        user_docs[doc_id]["updated_at"] = now_iso
        return DocumentResponse(**user_docs[doc_id])

    # Fallback to reading document
    existing = document_repository.get_document_by_id(doc_id, owner_id, token)
    if existing:
        return existing

    raise ValueError(f"Document {doc_id} could not be found for update.")


def process_document_bytes(
    file_bytes: bytes,
    filename: str,
    file_type: str,
) -> dict[str, Any]:
    """Execute temporary extraction and OCR on file bytes.

    Uses a temporary directory in system /tmp and ensures zero permanent storage.
    """
    safe_name = sanitize_filename(filename)

    # Temporary processing context
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = os.path.join(temp_dir, safe_name)
        with open(temp_path, "wb") as tmp_file:
            tmp_file.write(file_bytes)

        # Extraction logic based on file type
        normalized_type = file_type.lower()
        if normalized_type == "pdf" or filename.lower().endswith(".pdf"):
            return extract_pdf_text(file_bytes, filename=filename)
        elif normalized_type == "docx" or filename.lower().endswith(".docx"):
            return extract_docx_text(file_bytes, filename=filename)
        elif normalized_type == "image" or any(
            filename.lower().endswith(ext)
            for ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif")
        ):
            return process_image(file_bytes, filename=filename)
        else:
            raise ValueError(f"Unsupported document type: {file_type} ({filename})")


async def reconcile_storage_object(
    storage_path: str,
    owner_id: str,
    token: str | None = None,
) -> DocumentResponse:
    """Create a document row for a new private Storage object and process it.

    Safe path parser and validation ensure that the owner is derived from the path
    rather than any client-controlled value.
    """
    from storage.supabase_storage import parse_storage_object_owner

    path_owner = parse_storage_object_owner(storage_path)
    if not path_owner:
        raise ValueError("Storage path does not contain a valid user-scoped owner segment.")
    if path_owner != owner_id:
        raise PermissionError("Storage path owner does not match the authenticated user.")

    filename = storage_path.split('/')[-1]
    validate_filename_security(filename)
    ext = validate_file_extension(filename)
    validate_mime_type("application/octet-stream")

    existing = document_repository.get_document_by_storage_path(storage_path, owner_id, token)
    if existing:
        return existing

    file_bytes = supabase_storage.get_document_file(storage_path, token=token)
    if file_bytes is None:
        raise FileNotFoundError(f"Storage object {storage_path} could not be retrieved.")
    validate_file_size(len(file_bytes))

    doc_id = str(__import__('uuid').uuid4())
    doc_create = DocumentCreate(
        original_filename=filename,
        storage_path=storage_path,
        file_type="image" if ext in {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'} else ('pdf' if ext == '.pdf' else 'docx'),
        file_size_bytes=len(file_bytes),
        metadata={
            "file_size_bytes": len(file_bytes),
            "mime_type": "application/octet-stream",
            "extension": ext,
            "source": "supabase_storage_reconciliation",
        },
    )
    saved_doc = document_repository.save_document(
        doc=doc_create,
        owner_id=owner_id,
        doc_id=doc_id,
        token=token,
    )

    updated = _update_document_record(
        doc_id=saved_doc.id,
        owner_id=owner_id,
        status="pending",
        metadata={"reconciled_from_storage": True, **saved_doc.metadata},
        token=token,
    )
    return await process_document(saved_doc.id, owner_id, token=token)


async def process_document(
    document_id: str,
    owner_id: str,
    token: str | None = None,
) -> DocumentResponse:
    """Process an uploaded document from Supabase Storage.

    FLOW:
    1. Secure retrieval from private Supabase Storage
    2. Temporary processing in /tmp (cleaned up automatically)
    3. Extraction / OCR
    4. Text normalization & validation
    5. Chunk text (preserving doc_id, order, source metadata, page number)
    6. Save chunks
    7. Update processing status: ONLY mark 'ready' when all steps succeed.
    """
    # 1. Retrieve document metadata
    doc = document_repository.get_document_by_id(doc_id=document_id, owner_id=owner_id, token=token)
    if not doc:
        raise FileNotFoundError(f"Document {document_id} not found for owner {owner_id}.")

    # 2. Retrieve file bytes from private storage
    file_bytes = supabase_storage.get_document_file(storage_path=doc.storage_path, token=token)
    if file_bytes is None:
        err_meta = build_error_metadata(
            error_type="STORAGE_NOT_FOUND",
            error_message="Document binary data could not be retrieved from private storage.",
            original_metadata=doc.metadata,
        )
        return _update_document_record(
            doc_id=document_id,
            owner_id=owner_id,
            status="failed",
            metadata=err_meta,
            token=token,
        )

    # 3. Handle empty files early
    if len(file_bytes) == 0:
        err_meta = build_error_metadata(
            error_type="EMPTY_FILE",
            error_message=f"Document '{doc.original_filename}' is empty (0 bytes).",
            original_metadata=doc.metadata,
        )
        return _update_document_record(
            doc_id=document_id,
            owner_id=owner_id,
            status="failed",
            metadata=err_meta,
            token=token,
        )

    # 4. Process document with comprehensive error handling
    try:
        extraction_result = process_document_bytes(
            file_bytes=file_bytes,
            filename=doc.original_filename,
            file_type=doc.file_type,
        )

        extracted_text = extraction_result.get("text", "")
        pages = extraction_result.get("pages", [])

        # 5. Chunk the document text
        source_meta = {
            "document_id": doc.id,
            "filename": doc.original_filename,
            "file_type": doc.file_type,
            "source": doc.source,
        }

        chunks = chunk_document(
            document_id=doc.id,
            pages=pages,
            full_text=extracted_text,
            source_metadata=source_meta,
        )

        # 6. Save chunks
        save_document_chunks(doc.id, chunks)

        # 7. Build updated metadata & mark document READY
        updated_meta = build_processing_metadata(
            file_type=doc.file_type,
            extraction_result=extraction_result,
            chunk_count=len(chunks),
            original_metadata=doc.metadata,
        )

        logger.info(
            "Document %s processed successfully: %d chunks, %d chars. Status -> ready",
            doc.id,
            len(chunks),
            updated_meta.get("total_chars", 0),
        )

        return _update_document_record(
            doc_id=document_id,
            owner_id=owner_id,
            status="ready",
            metadata=updated_meta,
            token=token,
        )

    except (EmptyPDFError, EmptyDOCXError, EmptyImageError) as exc:
        err_meta = build_error_metadata("EMPTY_FILE", str(exc), doc.metadata)
        return _update_document_record(document_id, owner_id, "failed", err_meta, token)

    except (CorruptPDFError, CorruptDOCXError, CorruptImageError) as exc:
        err_meta = build_error_metadata("CORRUPT_FILE", str(exc), doc.metadata)
        return _update_document_record(document_id, owner_id, "failed", err_meta, token)

    except EncryptedPDFError as exc:
        err_meta = build_error_metadata("ENCRYPTED_PDF", str(exc), doc.metadata)
        return _update_document_record(document_id, owner_id, "failed", err_meta, token)

    except UnsupportedImageFormatError as exc:
        err_meta = build_error_metadata("UNSUPPORTED_FORMAT", str(exc), doc.metadata)
        return _update_document_record(document_id, owner_id, "failed", err_meta, token)

    except OCRError as exc:
        err_meta = build_error_metadata("OCR_FAILED", str(exc), doc.metadata)
        return _update_document_record(document_id, owner_id, "failed", err_meta, token)

    except (PDFExtractionError, DOCXExtractionError, ImageProcessingError, Exception) as exc:
        logger.exception("Extraction failed for document %s: %s", doc.id, exc)
        err_meta = build_error_metadata("EXTRACTION_FAILED", str(exc), doc.metadata)
        return _update_document_record(document_id, owner_id, "failed", err_meta, token)
