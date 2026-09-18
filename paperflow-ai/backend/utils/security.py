"""Security utilities for PaperFlow AI (Stage 21).

Provides:
- Dynamic cryptographically secure signing keys (no static hardcoded keys)
- HMAC-SHA256 document access signature generation and constant-time verification
- HMAC-SHA256 OAuth CSRF state token generation and verification
- Prompt injection defense for retrieved document text
- Sensitive data and secret masking for safe logging
- UUID format validation
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
import uuid
from typing import Any

logger = logging.getLogger("paperflow.security")

# Ephemeral runtime fallback secret if no environment secret is configured
# Generated once per process startup so it cannot be predicted across instances
_RUNTIME_SECRET = secrets.token_hex(32)

# OAuth state expiration: 15 minutes
OAUTH_STATE_EXPIRY_SECONDS = 900

# Known prompt injection and instruction override patterns in untrusted document text
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)\b(ignore|disregard|forget|override)\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|commands|rules)\b"),
    re.compile(r"(?i)\b(system\s+override|admin\s+override|developer\s+mode|dan\s+mode)\b"),
    re.compile(r"(?i)\b(you\s+are\s+now|new\s+system\s+instruction|system\s+prompt\s*:)\b"),
    re.compile(r"(?i)<\s*(system|instruction|admin)\s*>"),
    re.compile(r"(?i)\[\s*(system|instruction|admin)\s*\]"),
    re.compile(r"(?i)\b(assistant\s*:|human\s*:|user\s*:|system\s*:)\b"),
    re.compile(r"(?i)<\s*\|\s*im_start\s*\|\s*>|<\s*\|\s*im_end\s*\|\s*>"),
]


def get_application_secret() -> str:
    """Retrieve the application secret key for cryptographic operations.

    Uses SUPABASE_JWT_SECRET, SUPABASE_SERVICE_ROLE_KEY, or SECRET_KEY.
    Falls back to a secure random per-process secret — NEVER a hardcoded predictable string.
    """
    configured = (
        os.getenv("SECRET_KEY")
        or os.getenv("SUPABASE_JWT_SECRET")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )
    if configured and configured.strip():
        return configured.strip()
    return _RUNTIME_SECRET


# ---------------------------------------------------------------------------
# Signed Document URLs
# ---------------------------------------------------------------------------

def generate_document_access_signature(document_id: str, owner_id: str, expires_at: int) -> str:
    """Generate a tamper-proof HMAC-SHA256 signature for temporary document access."""
    secret = get_application_secret()
    payload = f"{document_id}:{owner_id}:{expires_at}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_document_access_signature(
    document_id: str,
    owner_id: str,
    expires_at: int,
    signature: str,
) -> bool:
    """Verify document access signature using constant-time comparison and expiration check."""
    now_ts = int(time.time())
    if now_ts > expires_at:
        return False

    expected_sig = generate_document_access_signature(document_id, owner_id, expires_at)
    return hmac.compare_digest(signature, expected_sig)


# ---------------------------------------------------------------------------
# OAuth CSRF State Token Generation & Verification
# ---------------------------------------------------------------------------

def generate_signed_oauth_state(user_id: str) -> str:
    """Generate a signed, time-bound OAuth CSRF state token bound to user_id.

    Format: user_id:timestamp:nonce:hmac_signature
    """
    secret = get_application_secret()
    timestamp = int(time.time())
    nonce = secrets.token_hex(8)
    data = f"{user_id}:{timestamp}:{nonce}"
    sig = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{data}:{sig}"


def verify_signed_oauth_state(state: str, max_age_seconds: int = OAUTH_STATE_EXPIRY_SECONDS) -> str | None:
    """Verify a signed OAuth CSRF state token and return the verified user_id.

    Returns user_id if signature is valid and timestamp is within max_age_seconds,
    or None if invalid, forged, or expired.
    """
    if not state or ":" not in state:
        return None

    parts = state.split(":")
    if len(parts) != 4:
        return None

    user_id, ts_str, nonce, sig = parts
    try:
        ts = int(ts_str)
    except ValueError:
        return None

    # Expiration check
    now = int(time.time())
    if max_age_seconds <= 0 or (now - ts) > max_age_seconds or ts > (now + 60):
        return None

    secret = get_application_secret()
    data = f"{user_id}:{ts_str}:{nonce}"
    expected_sig = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    if not hmac.compare_digest(sig, expected_sig):
        return None

    return user_id


# ---------------------------------------------------------------------------
# Prompt Injection Sanitization for Untrusted Documents
# ---------------------------------------------------------------------------

def sanitize_document_text_for_llm(text: str) -> str:
    """Sanitize retrieved document content before injecting into LLM context.

    Neutralizes prompt injection attempts, instruction override attacks,
    and role spoofing markers embedded within user documents.
    """
    if not text:
        return ""

    sanitized = text
    for pattern in PROMPT_INJECTION_PATTERNS:
        sanitized = pattern.sub("[POTENTIAL_PROMPT_INJECTION_FLAGGED_AND_FILTERED]", sanitized)

    return sanitized


# ---------------------------------------------------------------------------
# UUID and Secret Helpers
# ---------------------------------------------------------------------------

def is_valid_uuid(val: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def mask_secret(secret: str | None) -> str:
    """Mask sensitive tokens or API keys for safe debugging/logging."""
    if not secret:
        return "<none>"
    s = str(secret).strip()
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}...{s[-4:]}"
