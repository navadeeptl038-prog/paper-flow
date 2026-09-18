"""Document upload, management, processing, and vector search routes for PaperFlow AI.

Endpoints:
  POST   /api/documents/upload               — upload single or multiple documents
  GET    /api/documents                      — list authenticated user's documents
  GET    /api/documents/ocr/status           — check OCR dependency status
  POST   /api/documents/search               — semantic vector similarity search
  GET    /api/documents/{id}                 — get document metadata
  POST   /api/documents/{id}/process         — process an uploaded document (OCR/extraction/chunking)
  POST   /api/documents/{id}/embed           — generate and persist vector embeddings for chunks
  GET    /api/documents/{id}/chunks          — get chunks for a processed document
  DELETE /api/documents/{id}                 — delete a document
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from auth.authorization import require_user
from connectors.local_storage import process_file_upload
from document_processing.chunker import DocumentChunk
from document_processing.ocr import get_ocr_dependencies_status
from models.chunk import ChunkRecord, SearchQuery, SearchResponse
from models.document import DocumentResponse, DocumentUploadResponse
from models.user import AuthenticatedUser
from services import document_service, intent_service, vector_service
from storage import document_repository, supabase_storage
from utils import security

logger = logging.getLogger("paperflow.documents")

router = APIRouter(prefix="/api/documents", tags=["documents"])
_bearer = HTTPBearer(auto_error=False)


class DocumentItem(BaseModel):
    """Document search match item with actions."""

    id: str
    owner_id: str
    original_filename: str
    storage_path: str
    file_type: str
    processing_status: str
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    view_url: str
    download_url: str


class DocumentQueryResponse(BaseModel):
    """Structured response for document queries."""

    query: str
    intent: str
    category: str
    explicit_document_request: bool
    target_document_hint: str | None = None
    found: bool
    count: int
    documents: list[DocumentItem]
    message: str


class SignedAccessResponse(BaseModel):
    """Short-lived temporary access URLs for preview and download."""

    document_id: str
    filename: str
    view_url: str
    download_url: str
    storage_signed_url: str | None = None
    expires_in: int
    expires_at: int


def _generate_signature(document_id: str, owner_id: str, expires: int) -> str:
    """Generate time-limited HMAC-SHA256 signature for document access."""
    return security.generate_document_access_signature(document_id, owner_id, expires)


def _get_media_and_disposition(filename: str, action: str = "view") -> tuple[str, str]:
    """Determine MIME type and Content-Disposition.

    Rules:
      - PDF/image: browser preview (Content-Disposition: inline)
      - DOCX: safe download fallback (Content-Disposition: attachment)
      - Explicit download action: always attachment
    """
    ext = (filename.split(".")[-1] or "").lower()
    mime_map = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "heic": "image/heic",
        "heif": "image/heif",
    }
    media_type = mime_map.get(ext, "application/octet-stream")

    if action == "download" or ext == "docx":
        disposition = f'attachment; filename="{filename}"'
    else:
        disposition = f'inline; filename="{filename}"'

    return media_type, disposition


@router.get(
    "/ocr/status",
    summary="OCR dependencies status",
    description="Check availability of Tesseract OCR and image decoding dependencies.",
)
async def ocr_status() -> dict[str, Any]:
    """Return status of system OCR dependencies."""
    return get_ocr_dependencies_status()


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload documents",
    description="Upload single or multiple files (PDF, DOCX, JPG, PNG, WEBP, HEIC, HEIF) to private Supabase Storage.",
)
async def upload_documents(
    files: list[UploadFile] = File(..., description="One or more files to upload"),
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> DocumentUploadResponse:
    """Upload documents for the authenticated user."""
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided for upload.",
        )

    token = credentials.credentials if credentials else None
    uploaded_docs: list[DocumentResponse] = []

    for file in files:
        doc = await process_file_upload(
            upload_file=file,
            user_id=user.user_id,
            token=token,
        )
        uploaded_docs.append(doc)

    return DocumentUploadResponse(
        documents=uploaded_docs,
        count=len(uploaded_docs),
        message=f"Successfully uploaded {len(uploaded_docs)} document(s).",
    )


@router.get(
    "",
    response_model=list[DocumentResponse],
    summary="List documents",
    description="List all documents owned by the authenticated user.",
)
async def list_documents(
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> list[DocumentResponse]:
    """Retrieve all documents belonging to the authenticated user."""
    token = credentials.credentials if credentials else None
    return document_repository.list_user_documents(owner_id=user.user_id, token=token)


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Vector similarity search",
    description="Semantic vector similarity search across document chunks with top-k and threshold filtering.",
)
async def vector_search_endpoint(
    search_query: SearchQuery,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> SearchResponse:
    """Perform vector similarity search, strictly scoped to authenticated user."""
    token = credentials.credentials if credentials else None
    return await vector_service.search_vectors(
        search_query=search_query,
        user_id=user.user_id,
        token=token,
    )


@router.get(
    "/query",
    response_model=DocumentQueryResponse,
    summary="Document query intent and matching",
    description="Identifies document intent (e.g. 'Find my passport.', 'Find my ATM card.') and returns matching documents with View and Download links.",
)
async def query_documents(
    q: str = Query(..., description="User document query"),
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> DocumentQueryResponse:
    """Identify document query intent and find matching documents strictly owned by authenticated user."""
    token = credentials.credentials if credentials else None
    clean_q = q.strip()
    intent_res = intent_service.detect_intent(clean_q)

    # Search documents strictly for this authenticated owner
    matching_docs = document_repository.search_documents_by_keyword(
        owner_id=user.user_id,
        query=clean_q,
        target_hint=intent_res.target_document_hint,
        token=token,
    )

    doc_items: list[DocumentItem] = []
    for d in matching_docs:
        doc_items.append(
            DocumentItem(
                id=d.id,
                owner_id=d.owner_id,
                original_filename=d.original_filename,
                storage_path=d.storage_path,
                file_type=d.file_type,
                processing_status=d.processing_status,
                source=d.source,
                metadata=d.metadata,
                created_at=d.created_at,
                updated_at=d.updated_at,
                view_url=f"/api/documents/{d.id}/view",
                download_url=f"/api/documents/{d.id}/download",
            )
        )

    found = len(doc_items) > 0
    msg = (
        f"Found {len(doc_items)} matching document(s)."
        if found
        else f"No document matching '{clean_q}' found."
    )

    return DocumentQueryResponse(
        query=clean_q,
        intent=intent_res.intent.value,
        category=intent_res.category.value,
        explicit_document_request=intent_res.explicit_document_request,
        target_document_hint=intent_res.target_document_hint,
        found=found,
        count=len(doc_items),
        documents=doc_items,
        message=msg,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document metadata",
)
async def get_document(
    document_id: str,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> DocumentResponse:
    """Retrieve document metadata, strictly enforcing owner_id == user.user_id."""
    token = credentials.credentials if credentials else None
    doc = document_repository.get_document_by_id(
        doc_id=document_id,
        owner_id=user.user_id,
        token=token,
    )
    if not doc:
        other_doc = document_repository.get_document_any_owner(document_id)
        if other_doc and other_doc.owner_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this document.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return doc


@router.get(
    "/{document_id}/view",
    summary="View document (browser preview / download fallback)",
    description="Streams document for inline browser preview (PDF/image) or safe download fallback (DOCX). Enforces ownership.",
)
async def view_document_endpoint(
    document_id: str,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Response:
    """Stream document for browser preview. Never returns another user's file."""
    token = credentials.credentials if credentials else None

    # Ownership verification
    doc = document_repository.get_document_by_id(
        doc_id=document_id,
        owner_id=user.user_id,
        token=token,
    )
    if not doc:
        other_doc = document_repository.get_document_any_owner(document_id)
        if other_doc and other_doc.owner_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this document.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    file_bytes = supabase_storage.get_document_file(doc.storage_path, token=token)
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original file could not be retrieved from storage.",
        )

    media_type, disposition = _get_media_and_disposition(doc.original_filename, action="view")

    headers = {
        "Content-Disposition": disposition,
        "Content-Length": str(len(file_bytes)),
        "Cache-Control": "private, no-cache, no-store, must-revalidate",
    }
    return Response(content=file_bytes, media_type=media_type, headers=headers)


@router.get(
    "/{document_id}/download",
    summary="Download original document",
    description="Streams original file with attachment disposition. Strictly enforces ownership.",
)
async def download_document_endpoint(
    document_id: str,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Response:
    """Stream original file for download. Strictly enforces ownership."""
    token = credentials.credentials if credentials else None

    # Ownership verification
    doc = document_repository.get_document_by_id(
        doc_id=document_id,
        owner_id=user.user_id,
        token=token,
    )
    if not doc:
        other_doc = document_repository.get_document_any_owner(document_id)
        if other_doc and other_doc.owner_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this document.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    file_bytes = supabase_storage.get_document_file(doc.storage_path, token=token)
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original file could not be retrieved from storage.",
        )

    media_type, disposition = _get_media_and_disposition(doc.original_filename, action="download")

    headers = {
        "Content-Disposition": disposition,
        "Content-Length": str(len(file_bytes)),
        "Cache-Control": "private, no-cache, no-store, must-revalidate",
    }
    return Response(content=file_bytes, media_type=media_type, headers=headers)


@router.post(
    "/{document_id}/signed-access",
    response_model=SignedAccessResponse,
    summary="Generate temporary short-lived signed access URL",
    description="Generates short-lived signed URLs for temporary viewing/downloading without exposing permanent links or public storage.",
)
async def create_signed_access(
    document_id: str,
    expires_in: int = Query(300, ge=10, le=3600, description="Expiration in seconds (default 300s)"),
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> SignedAccessResponse:
    """Generate short-lived signed access URL for private document."""
    token = credentials.credentials if credentials else None

    doc = document_repository.get_document_by_id(
        doc_id=document_id,
        owner_id=user.user_id,
        token=token,
    )
    if not doc:
        other_doc = document_repository.get_document_any_owner(document_id)
        if other_doc and other_doc.owner_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this document.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    now_ts = int(time.time())
    expires_at = now_ts + expires_in
    sig = _generate_signature(doc.id, user.user_id, expires_at)

    view_url = f"/api/documents/{doc.id}/preview?expires={expires_at}&sig={sig}&action=view"
    download_url = f"/api/documents/{doc.id}/preview?expires={expires_at}&sig={sig}&action=download"

    storage_signed_url = supabase_storage.create_signed_url(
        doc.storage_path,
        expires_in_seconds=expires_in,
        token=token,
    )

    return SignedAccessResponse(
        document_id=doc.id,
        filename=doc.original_filename,
        view_url=view_url,
        download_url=download_url,
        storage_signed_url=storage_signed_url,
        expires_in=expires_in,
        expires_at=expires_at,
    )


@router.get(
    "/{document_id}/preview",
    summary="Access file via short-lived signed URL",
    description="Streams document if the signature and expiration timestamp are valid. Enforces time-bound temporary access.",
)
async def preview_document_signed(
    document_id: str,
    expires: int = Query(..., description="Expiration timestamp (unix epoch seconds)"),
    sig: str = Query(..., description="HMAC SHA-256 access signature"),
    action: str = Query("view", pattern="^(view|download)$", description="Access action: view or download"),
) -> Response:
    """Stream document via temporary short-lived signed URL without exposing storage publicly."""
    now_ts = int(time.time())

    # 1. Check expiration
    if now_ts > expires:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access expired or invalid.",
        )

    # 2. Retrieve document metadata
    doc = document_repository.get_document_any_owner(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    # 3. Verify signature against document owner
    if not security.verify_document_access_signature(doc.id, doc.owner_id, expires, sig):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access expired or invalid.",
        )

    # 4. Fetch file bytes
    file_bytes = supabase_storage.get_document_file(doc.storage_path)
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original file could not be retrieved from storage.",
        )

    media_type, disposition = _get_media_and_disposition(doc.original_filename, action=action)

    headers = {
        "Content-Disposition": disposition,
        "Content-Length": str(len(file_bytes)),
        "Cache-Control": "private, no-cache, no-store, must-revalidate",
    }
    return Response(content=file_bytes, media_type=media_type, headers=headers)


@router.post(
    "/{document_id}/process",
    response_model=DocumentResponse,
    summary="Process document",
    description="Retrieve document from Supabase Storage, run extraction/OCR, create chunks, and update status to Ready.",
)
async def process_document_endpoint(
    document_id: str,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> DocumentResponse:
    """Process an uploaded document for the authenticated user."""
    token = credentials.credentials if credentials else None

    # Check ownership
    doc = document_repository.get_document_by_id(
        doc_id=document_id,
        owner_id=user.user_id,
        token=token,
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    try:
        updated_doc = await document_service.process_document(
            document_id=document_id,
            owner_id=user.user_id,
            token=token,
        )

        # If document processed successfully, also embed and persist chunks
        if updated_doc.processing_status == "ready":
            chunks = document_service.get_document_chunks(document_id, user.user_id)
            if chunks:
                await vector_service.embed_and_store_chunks(
                    document_id=document_id,
                    owner_id=user.user_id,
                    chunks=chunks,
                    token=token,
                )

        return updated_doc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Processing endpoint error for %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document processing failed: {exc}",
        )


@router.post(
    "/{document_id}/embed",
    response_model=list[ChunkRecord],
    summary="Embed document chunks",
    description="Generate and persist 384-dimensional dense vector embeddings for document chunks.",
)
async def embed_document_endpoint(
    document_id: str,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> list[ChunkRecord]:
    """Generate and store embeddings for chunks of a document."""
    token = credentials.credentials if credentials else None

    doc = document_repository.get_document_by_id(
        doc_id=document_id,
        owner_id=user.user_id,
        token=token,
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    chunks = document_service.get_document_chunks(document_id, user.user_id)
    if not chunks:
        # Check database
        db_chunks = document_repository.get_document_chunks_by_doc(document_id, user.user_id, token)
        if db_chunks:
            return db_chunks
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document has no chunks. Process the document first.",
        )

    return await vector_service.embed_and_store_chunks(
        document_id=document_id,
        owner_id=user.user_id,
        chunks=chunks,
        token=token,
    )


@router.get(
    "/{document_id}/chunks",
    response_model=list[DocumentChunk],
    summary="Get document chunks",
    description="Retrieve all text chunks for a processed document.",
)
async def get_document_chunks_endpoint(
    document_id: str,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> list[DocumentChunk]:
    """Retrieve indexed chunks, strictly enforcing owner_id."""
    token = credentials.credentials if credentials else None
    doc = document_repository.get_document_by_id(
        doc_id=document_id,
        owner_id=user.user_id,
        token=token,
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    return document_service.get_document_chunks(document_id=document_id, owner_id=user.user_id)


@router.delete(
    "/{document_id}",
    summary="Delete document",
)
async def delete_document(
    document_id: str,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Delete document and its storage object, strictly enforcing owner_id."""
    token = credentials.credentials if credentials else None
    doc = document_repository.get_document_by_id(
        doc_id=document_id,
        owner_id=user.user_id,
        token=token,
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    # Remove storage file
    supabase_storage.delete_document_file(doc.storage_path, token=token)

    # Remove database record
    document_repository.delete_document(document_id, owner_id=user.user_id, token=token)

    return {"deleted": True, "id": document_id}
