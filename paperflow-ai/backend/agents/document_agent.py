"""Document Agent for PaperFlow AI.

This agent is limited to the authenticated user's original documents. It
searches the existing document metadata, validates readiness, and exposes only
private backend access URLs for view/download actions. It never creates or
returns a replacement document and never bypasses the authenticated owner
identity.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from typing import Any

from models.document import DocumentResponse
from storage import document_repository, supabase_storage


@dataclass
class DocumentMatch:
    """Single matching document result."""

    id: str
    filename: str
    document_type: str
    source: str = "local_storage"
    mime_type: str = "application/octet-stream"
    status: str = "ready"
    view_available: bool = True
    download_available: bool = True
    owner_id: str = ""
    storage_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentSearchResult:
    """Structured search response returned by the document agent."""

    query: str
    found: bool
    documents: list[DocumentMatch] = field(default_factory=list)
    message: str = ""


class DocumentAgent:
    """Finds and exposes original user documents without exposing storage secrets."""

    @staticmethod
    def _infer_document_type(filename: str, file_type: str | None = None) -> str:
        lowered = (filename or "").lower()
        document_type_map = {
            "passport": "passport",
            "aadhar": "aadhar",
            "aadhaar": "aadhaar",
            "pan": "pan",
            "license": "license",
            "driving": "driving_license",
            "bank": "bank_statement",
            "statement": "bank_statement",
            "resume": "resume",
            "visa": "visa",
            "insurance": "insurance",
            "id": "id_document",
        }
        for keyword, value in document_type_map.items():
            if keyword in lowered:
                return value
        return (file_type or "document").lower()

    @staticmethod
    def _document_is_ready(doc: DocumentResponse) -> bool:
        status = (doc.processing_status or "").lower()
        return status in {"ready", "uploaded"}

    def search_documents(
        self,
        *,
        user_id: str,
        query: str,
        client_user_id: str | None = None,
        token: str | None = None,
    ) -> DocumentSearchResult:
        """Search only the authenticated user's ready documents.

        The authenticated user_id is always authoritative. Any client-supplied
        user_id is ignored; it cannot override the verified identity.
        """
        if not user_id:
            raise ValueError("user_id is required and must come from the authenticated identity.")

        # Ignore any client-supplied identity override.
        _ = client_user_id
        clean_q = (query or "").strip()
        if not clean_q:
            return DocumentSearchResult(query="", found=False, documents=[], message="No document query was provided.")

        matched = document_repository.search_documents_by_keyword(
            owner_id=user_id,
            query=clean_q,
            token=token,
        )

        ready_docs: list[DocumentMatch] = []
        seen: set[str] = set()
        for doc in matched:
            if doc.owner_id != user_id:
                continue
            if not self._document_is_ready(doc):
                continue
            if doc.id in seen:
                continue
            seen.add(doc.id)
            mime_type = (doc.metadata or {}).get("mime_type") or mimetypes.guess_type(doc.original_filename)[0] or "application/octet-stream"
            ready_docs.append(
                DocumentMatch(
                    id=doc.id,
                    filename=doc.original_filename,
                    document_type=self._infer_document_type(doc.original_filename, doc.file_type),
                    source=doc.source or "local_storage",
                    mime_type=mime_type,
                    status=doc.processing_status,
                    view_available=True,
                    download_available=True,
                    owner_id=doc.owner_id,
                    storage_path=doc.storage_path,
                    metadata=doc.metadata or {},
                )
            )

        if not ready_docs:
            return DocumentSearchResult(
                query=clean_q,
                found=False,
                documents=[],
                message="I couldn't find a matching document in your connected sources.",
            )

        return DocumentSearchResult(
            query=clean_q,
            found=True,
            documents=ready_docs,
            message=f"Found {len(ready_docs)} matching document(s).",
        )

    def get_document_access(
        self,
        *,
        document_id: str,
        user_id: str,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Return private backend access routes for an owned document.

        Never exposes a permanent public Storage URL or any service-role secret.
        """
        if not user_id:
            raise ValueError("user_id is required and must come from the authenticated identity.")

        doc = document_repository.get_document_by_id(doc_id=document_id, owner_id=user_id, token=token)
        if not doc:
            other_doc = document_repository.get_document_any_owner(document_id)
            if other_doc and other_doc.owner_id != user_id:
                raise PermissionError("You do not have permission to access this document.")
            raise FileNotFoundError("Document not found.")

        if not self._document_is_ready(doc):
            raise ValueError(f"Document '{doc.original_filename}' is not ready for access.")

        return {
            "document_id": doc.id,
            "filename": doc.original_filename,
            "document_type": self._infer_document_type(doc.original_filename, doc.file_type),
            "source": doc.source or "local_storage",
            "view_url": f"/api/documents/{doc.id}/view",
            "download_url": f"/api/documents/{doc.id}/download",
            "storage_path": doc.storage_path,
            "status": doc.processing_status,
            "view_available": True,
            "download_available": True,
        }

    def download_document(
        self,
        *,
        document_id: str,
        user_id: str,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Return the original file bytes and metadata for an authenticated user's document."""
        if not user_id:
            raise ValueError("user_id is required and must come from the authenticated identity.")

        doc = document_repository.get_document_by_id(doc_id=document_id, owner_id=user_id, token=token)
        if not doc:
            other_doc = document_repository.get_document_any_owner(document_id)
            if other_doc and other_doc.owner_id != user_id:
                raise PermissionError("You do not have permission to access this document.")
            raise FileNotFoundError("Document not found.")

        if not self._document_is_ready(doc):
            raise ValueError(f"Document '{doc.original_filename}' is not ready for download.")

        file_bytes = supabase_storage.get_document_file(doc.storage_path, token=token)
        if file_bytes is None:
            raise FileNotFoundError("Original file could not be retrieved from storage.")

        content_type = (doc.metadata or {}).get("mime_type") or mimetypes.guess_type(doc.original_filename)[0] or "application/octet-stream"
        return {
            "document_id": doc.id,
            "filename": doc.original_filename,
            "content_type": content_type,
            "size_bytes": len(file_bytes),
            "storage_path": doc.storage_path,
            "bytes": file_bytes,
        }
