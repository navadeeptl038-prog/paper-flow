"""Utility functions for file handling, path creation, and checksum calculation."""

from __future__ import annotations

import hashlib
import os
import re
import uuid


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename to only contain safe ASCII characters, numbers, dots, dashes, and underscores."""
    base_name = os.path.basename(filename)
    root, ext = os.path.splitext(base_name)

    # Remove any characters other than alphanumeric, hyphens, underscores
    clean_root = re.sub(r"[^a-zA-Z0-9_\-]", "_", root)
    clean_root = re.sub(r"_+", "_", clean_root).strip("_")

    if not clean_root:
        clean_root = f"file_{uuid.uuid4().hex[:8]}"

    clean_ext = ext.lower().strip()
    return f"{clean_root}{clean_ext}"


def build_user_storage_path(user_id: str, doc_id: str, filename: str) -> str:
    """Construct a user-scoped, private storage path.

    Format: <user_id>/<doc_id>/<safe_filename>
    Prevents path traversal and guarantees user data isolation.
    """
    safe_name = sanitize_filename(filename)
    clean_user = str(user_id).strip()
    clean_doc = str(doc_id).strip()
    return f"{clean_user}/{clean_doc}/{safe_name}"


def compute_sha256(data: bytes) -> str:
    """Compute hex SHA-256 hash of file content."""
    return hashlib.sha256(data).hexdigest()


def infer_file_type(extension: str) -> str:
    """Classify the document into a high-level file type."""
    ext = extension.lower().strip()
    if ext == ".pdf":
        return "pdf"
    if ext in {".docx", ".doc"}:
        return "docx"
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}:
        return "image"
    return "document"
