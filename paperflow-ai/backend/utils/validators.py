"""Validation helpers for file uploads in PaperFlow AI.

Enforces:
- Allowed file extensions (PDF, DOCX, JPG, JPEG, PNG, WEBP, HEIC, HEIF)
- Allowed MIME types
- Maximum file size (50MB)
- Path traversal prevention
- Dangerous character sanitization
"""

from __future__ import annotations

import os
import re
import urllib.parse
from fastapi import HTTPException, status

# Allowed extensions (lowercase)
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".heic",
    ".heif",
}

# Dangerous executable or script extensions that must never be present
DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".bash", ".bin", ".py", ".rb", ".js",
    ".vbs", ".ps1", ".msi", ".jar", ".com", ".scr", ".pif", ".cpl", ".dll",
}

# Windows reserved device names
WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}

# Allowed MIME types
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "image/jpeg",
    "image/pjpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/heic-sequence",
    "image/heif-sequence",
    "application/octet-stream",  # Often sent by browsers for HEIC / DOCX
}

# Maximum file size: 50 MB
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

# Path traversal check pattern
TRAVERSAL_PATTERN = re.compile(r"(\.\./|\.\.\\|[\x00-\x1f]|\.\.$|/\.\./|\\\.\\\.)")


def validate_file_extension(filename: str) -> str:
    """Validate that the file extension is one of the supported formats.

    Returns the clean lowercase extension (e.g. '.pdf').
    Raises HTTPException 400 if invalid.
    """
    if not filename or not filename.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename cannot be empty.",
        )

    # Decode and check for multiple extensions
    unquoted = urllib.parse.unquote(filename.strip())
    parts = unquoted.lower().split(".")
    if len(parts) > 2:
        for ext_part in parts[1:]:
            dotted = f".{ext_part}"
            if dotted in DANGEROUS_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Dangerous file extension '{dotted}' detected in filename.",
                )

    ext = os.path.splitext(unquoted)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File type '{ext}' is not supported. "
                f"Supported formats: PDF, DOCX, JPG, JPEG, PNG, WEBP, HEIC, HEIF."
            ),
        )
    return ext


def validate_mime_type(content_type: str | None) -> str:
    """Validate that the reported MIME type is acceptable."""
    if not content_type:
        return "application/octet-stream"

    clean_mime = content_type.split(";")[0].strip().lower()
    if clean_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"MIME type '{clean_mime}' is not permitted.",
        )
    return clean_mime


def validate_file_size(size_bytes: int) -> None:
    """Validate that the file size is within the allowed 50MB limit."""
    if size_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes).",
        )
    if size_bytes > MAX_FILE_SIZE_BYTES:
        max_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum allowed size of {max_mb} MB.",
        )


def validate_filename_security(filename: str) -> str:
    r"""Check for path traversal, control characters, or malicious filename patterns.

    Enforces:
    - URL decoding
    - Null-byte rejection
    - Path traversal rejection (../, ..\, /../)
    - Windows reserved device name rejection (CON, PRN, AUX, NUL)
    - Length limits (max 255 characters)
    - Dangerous double extension rejection
    """
    if not filename or not filename.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: filename cannot be empty.",
        )

    # 1. Decode URL-encoded characters (e.g. %2e%2e%2f)
    decoded = urllib.parse.unquote(filename.strip())

    # 2. Check for null bytes and control characters
    if "\x00" in decoded or any(ord(c) < 32 for c in decoded):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: control characters and null bytes are prohibited.",
        )

    # 3. Path traversal patterns: strictly reject any traversal or separator characters
    if TRAVERSAL_PATTERN.search(decoded) or ".." in decoded or "/" in decoded or "\\" in decoded:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: path traversal sequences and directory separators are strictly prohibited.",
        )

    # 4. Length check
    if len(decoded) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: filename exceeds maximum length of 255 characters.",
        )

    # 5. Windows reserved device names
    name_root = os.path.splitext(decoded)[0].lower()
    if name_root in WINDOWS_RESERVED_NAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid filename: '{name_root}' is a reserved system name.",
        )

    clean_name = os.path.basename(decoded).strip()
    if not clean_name or clean_name in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    return clean_name

