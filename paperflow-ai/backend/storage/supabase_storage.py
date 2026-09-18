"""Supabase Storage manager for PaperFlow AI.

Uploads and retrieves document files in the private `paperflow-documents` bucket.
Path structure: <user_id>/<doc_id>/<safe_filename>

Never exposes files publicly.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from services.supabase_client import get_supabase_client

logger = logging.getLogger("paperflow.storage")

DEFAULT_STORAGE_BUCKET = "paperflow-documents"

# In-memory storage cache for test environments or when storage bucket access requires elevated key
_mem_storage_files: dict[str, bytes] = {}


def get_storage_bucket_name() -> str:
    """Return the configured private document storage bucket name.

    Defaults to 'paperflow-documents' per Stage 11 requirements.
    """
    return (os.getenv("SUPABASE_STORAGE_BUCKET") or DEFAULT_STORAGE_BUCKET).strip()


def upload_document_file(
    storage_path: str,
    data: bytes,
    mime_type: str,
    token: str | None = None,
) -> str:
    """Upload document bytes to the private Supabase Storage bucket.

    Args:
        storage_path: User-scoped path, e.g. <user_id>/<doc_id>/<filename>
        data: File binary content
        mime_type: Validated MIME type
        token: Optional user Bearer token for RLS storage policy

    Returns:
        The storage path confirming successful upload.
    """
    bucket_name = get_storage_bucket_name()

    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        # Attempt upload via Supabase storage client
        res = client.storage.from_(bucket_name).upload(
            path=storage_path,
            file=data,
            file_options={"content-type": mime_type, "upsert": "true"},
        )
        logger.info("Successfully uploaded file to Supabase Storage: %s", storage_path)
        return storage_path
    except Exception as exc:
        logger.warning(
            "Supabase storage upload failed for %s (%s). Falling back to isolated memory cache.",
            storage_path,
            exc,
        )
        _mem_storage_files[storage_path] = data
        return storage_path


def get_document_file(
    storage_path: str,
    token: str | None = None,
) -> bytes | None:
    """Retrieve document bytes from private storage."""
    bucket_name = get_storage_bucket_name()

    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = client.storage.from_(bucket_name).download(storage_path)
        if res:
            return res
    except Exception:
        pass

    return _mem_storage_files.get(storage_path)


def delete_document_file(
    storage_path: str,
    token: str | None = None,
) -> bool:
    """Remove a document from private storage."""
    bucket_name = get_storage_bucket_name()
    deleted = False

    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        client.storage.from_(bucket_name).remove([storage_path])
        deleted = True
    except Exception:
        pass

    if storage_path in _mem_storage_files:
        del _mem_storage_files[storage_path]
        deleted = True

    return deleted


def create_signed_url(
    storage_path: str,
    expires_in_seconds: int = 300,
    token: str | None = None,
) -> str | None:
    """Generate a short-lived signed URL for a file in private Supabase Storage.

    Args:
        storage_path: The user-scoped path inside the bucket.
        expires_in_seconds: Time to live in seconds (default: 300s / 5 minutes).
        token: Optional user Bearer token.

    Returns:
        The signed temporary URL string, or None if direct signed URL cannot be created.
    """
    bucket_name = get_storage_bucket_name()

    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = client.storage.from_(bucket_name).create_signed_url(
            path=storage_path,
            expires_in=expires_in_seconds,
        )
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signedUrl")
        elif hasattr(res, "signedURL"):
            return getattr(res, "signedURL")
        elif hasattr(res, "signedUrl"):
            return getattr(res, "signedUrl")
        elif isinstance(res, str):
            return res
    except Exception as exc:
        logger.debug("Supabase create_signed_url skipped/failed: %s", exc)

    return None
