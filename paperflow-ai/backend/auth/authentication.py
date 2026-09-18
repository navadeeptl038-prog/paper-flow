"""Backend JWT authentication for PaperFlow AI.

Validates Supabase-issued JWTs using Supabase's current supported verification mechanisms:
1. JWKS-based asymmetric signature verification (ES256/RS256) using Supabase's published JWKS
   endpoint ({SUPABASE_URL}/auth/v1/.well-known/jwks.json).
2. Direct token validation via the Supabase Auth API (client.auth.get_user(jwt)).
3. Symmetric HS256 validation fallback if SUPABASE_JWT_SECRET is configured.

Security principles:
  - user identity comes ONLY from verified claims ('sub' / user UUID)
  - secrets and tokens are never logged or exposed in API responses
  - missing, expired, or invalid tokens are rejected with HTTP 401
  - never trust a user_id supplied directly by the client
"""

from __future__ import annotations

import logging
import os
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from models.user import AuthenticatedUser
from services.supabase_client import get_supabase_client

logger = logging.getLogger("paperflow.auth")

# FastAPI security scheme — extracts Bearer token from Authorization header.
# auto_error=False lets us return a clean 401 message.
_bearer = HTTPBearer(auto_error=False)

_SUPABASE_AUDIENCE = "authenticated"
_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient | None:
    """Lazily initialize and return the PyJWKClient for the configured Supabase URL."""
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client

    supabase_url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    if not supabase_url:
        return None

    jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"
    try:
        _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True, max_cached_keys=16)
        return _jwks_client
    except Exception as exc:
        logger.warning("Could not initialize Supabase PyJWKClient: %s", exc)
        return None


def verify_supabase_jwt(token: str) -> AuthenticatedUser:
    """Verify a Supabase JWT and return the decoded AuthenticatedUser identity.

    Uses Supabase's modern JWKS public key verification first, falls back to
    the Supabase Auth API (get_user), and optionally supports legacy HS256
    symmetric secret if SUPABASE_JWT_SECRET is present.

    Args:
        token: Raw Bearer JWT string from the request.

    Returns:
        AuthenticatedUser populated from verified claims.

    Raises:
        HTTPException 401: Token is missing, expired, or invalid.
    """
    if not token or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is missing.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # -------------------------------------------------------------------------
    # 1. JWKS Asymmetric Verification (Modern Supabase default: ES256 / RS256)
    # -------------------------------------------------------------------------
    jwks = _get_jwks_client()
    if jwks is not None:
        try:
            signing_key = jwks.get_signing_key_from_jwt(token)
            payload: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience=_SUPABASE_AUDIENCE,
            )
            sub = payload.get("sub")
            if sub:
                return AuthenticatedUser(
                    user_id=str(sub),
                    email=payload.get("email"),
                    role=payload.get("role", "authenticated"),
                    aal=payload.get("aal"),
                )
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your session has expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidAudienceError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token audience is invalid.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception:
            # Fall through to Supabase Auth API verification
            pass

    # -------------------------------------------------------------------------
    # 2. Supabase Auth API Verification (client.auth.get_user)
    # -------------------------------------------------------------------------
    try:
        supabase_client = get_supabase_client()
        response = supabase_client.auth.get_user(token)
        if response and response.user:
            u = response.user
            return AuthenticatedUser(
                user_id=str(u.id),
                email=getattr(u, "email", None),
                role=getattr(u, "role", "authenticated") or "authenticated",
                aal=getattr(u, "aal", None),
            )
    except HTTPException:
        raise
    except Exception as exc:
        msg = str(exc).lower()
        if "expired" in msg:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your session has expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Invalid / unauthorized
        logger.debug("Supabase get_user validation failed: %s", exc)

    # -------------------------------------------------------------------------
    # 3. Optional Legacy HS256 Secret Fallback
    # -------------------------------------------------------------------------
    jwt_secret = (os.getenv("SUPABASE_JWT_SECRET") or "").strip()
    if jwt_secret:
        try:
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                audience=_SUPABASE_AUDIENCE,
            )
            sub = payload.get("sub")
            if sub:
                return AuthenticatedUser(
                    user_id=str(sub),
                    email=payload.get("email"),
                    role=payload.get("role", "authenticated"),
                    aal=payload.get("aal"),
                )
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your session has expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception:
            pass

    # All verification attempts failed — reject with 401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    """FastAPI dependency: extracts and verifies the Bearer token from the request.

    Raises:
        HTTPException 401: If credentials are missing or the token is invalid/expired.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return verify_supabase_jwt(credentials.credentials)
