"""Centralized Supabase client for the PaperFlow AI backend.

Credentials are loaded exclusively from environment variables.
Never import this module in frontend code — it uses service-role secrets.

Usage:
    from services.supabase_client import get_supabase_client, check_supabase_config

    client = get_supabase_client()
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("paperflow.supabase")

_client = None


def _get_url() -> str:
    """Return SUPABASE_URL, raising clearly if missing."""
    url = (os.getenv("SUPABASE_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "SUPABASE_URL is not set. "
            "Add it to backend/.env (see backend/.env.example)."
        )
    if not url.startswith("https://"):
        raise RuntimeError(
            f"SUPABASE_URL must start with 'https://', got: {url[:20]}... "
            "Check backend/.env."
        )
    return url


def _get_key() -> str:
    """Return the best available backend key (service role preferred over anon).

    SUPABASE_SERVICE_ROLE_KEY gives full RLS bypass for backend operations.
    Falls back to SUPABASE_ANON_KEY when service role is not configured yet.
    Never exposes the key value in logs or exceptions.
    """
    service_role = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if service_role:
        return service_role

    anon = (os.getenv("SUPABASE_ANON_KEY") or "").strip()
    if anon:
        logger.warning(
            "SUPABASE_SERVICE_ROLE_KEY is not set — falling back to SUPABASE_ANON_KEY. "
            "Backend operations requiring elevated privileges will fail."
        )
        return anon

    raise RuntimeError(
        "Neither SUPABASE_SERVICE_ROLE_KEY nor SUPABASE_ANON_KEY is set. "
        "Add at least one to backend/.env (see backend/.env.example)."
    )


def check_supabase_config() -> dict[str, str | bool]:
    """Validate Supabase configuration without making any network calls.

    Returns a dict with:
        url_set: bool — SUPABASE_URL is present and https
        service_role_set: bool — SUPABASE_SERVICE_ROLE_KEY is present
        anon_key_set: bool — SUPABASE_ANON_KEY is present
        bucket: str | None — SUPABASE_STORAGE_BUCKET value (name only, safe to log)

    Raises RuntimeError with a helpful, secret-free message if URL is missing.
    """
    url = _get_url()  # raises if missing / invalid
    service_role = bool((os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip())
    anon_key = bool((os.getenv("SUPABASE_ANON_KEY") or "").strip())
    bucket = (os.getenv("SUPABASE_STORAGE_BUCKET") or "").strip() or None

    if not service_role and not anon_key:
        raise RuntimeError(
            "Neither SUPABASE_SERVICE_ROLE_KEY nor SUPABASE_ANON_KEY is set. "
            "Add at least one to backend/.env."
        )

    return {
        "url_set": True,
        "url_host": url.replace("https://", "").split("/")[0],  # hostname only, safe to log
        "service_role_set": service_role,
        "anon_key_set": anon_key,
        "bucket": bucket,
    }


def get_supabase_client():
    """Return the singleton Supabase client, creating it on first call.

    Credentials come from SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
    (falls back to SUPABASE_ANON_KEY). Never exposes credential values.

    Raises:
        RuntimeError: If required environment variables are not set.
        ImportError: If the supabase package is not installed.
    """
    global _client
    if _client is not None:
        return _client

    try:
        import supabase  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "The 'supabase' package is not installed. "
            "Run: pip install -r backend/requirements.txt"
        ) from exc

    url = _get_url()
    key = _get_key()

    _client = supabase.create_client(url, key)
    logger.info(
        "Supabase client initialized for project host: %s",
        url.replace("https://", "").split("/")[0],
    )
    return _client


def reset_client() -> None:
    """Reset the cached singleton client (used in tests to re-initialize with different config)."""
    global _client
    _client = None
