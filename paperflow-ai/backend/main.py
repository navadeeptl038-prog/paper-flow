"""FastAPI application foundation for PaperFlow AI."""

import logging
import os

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from routes.auth import router as auth_router
from routes.chat import router as chat_router
from routes.connectors import router as connectors_router
from routes.documents import router as documents_router


load_dotenv()
logger = logging.getLogger("paperflow")

# Local development default when CORS_ORIGINS / FRONTEND_URL are unset.
# Production must set CORS_ORIGINS explicitly (comma-separated frontend origins).
_DEFAULT_DEV_ORIGIN = "http://localhost:5173"
_DEFAULT_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
_DEFAULT_HEADERS = ["Content-Type", "Authorization", "Accept"]


def _configured_origins() -> list[str]:
	"""Resolve allowed CORS origins from environment settings."""
	raw = (os.getenv("CORS_ORIGINS") or "").strip()
	if raw:
		return [origin.strip() for origin in raw.split(",") if origin.strip()]

	frontend = (os.getenv("FRONTEND_URL") or _DEFAULT_DEV_ORIGIN).strip()
	return [frontend] if frontend else [_DEFAULT_DEV_ORIGIN]


def _configured_methods() -> list[str]:
	raw = (os.getenv("CORS_ALLOW_METHODS") or "").strip()
	if not raw:
		return list(_DEFAULT_METHODS)
	return [method.strip().upper() for method in raw.split(",") if method.strip()]


def _configured_headers() -> list[str]:
	raw = (os.getenv("CORS_ALLOW_HEADERS") or "").strip()
	if not raw:
		return list(_DEFAULT_HEADERS)
	return [header.strip() for header in raw.split(",") if header.strip()]


class HealthResponse(BaseModel):
	status: str


app = FastAPI(
	title=os.getenv("APP_NAME", "PaperFlow AI"),
	version=os.getenv("APP_VERSION", "0.1.0"),
)

origins = _configured_origins()
allow_all_origins = "*" in origins
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"] if allow_all_origins else origins,
	allow_credentials=not allow_all_origins,
	allow_methods=_configured_methods(),
	allow_headers=_configured_headers(),
)


api_router = APIRouter()


@api_router.get("/health", response_model=HealthResponse)
@api_router.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
	return HealthResponse(status="ok")


class StatusResponse(BaseModel):
	app: str
	version: str
	supabase_url_configured: bool
	supabase_key_configured: bool


@api_router.get("/api/status", response_model=StatusResponse)
async def status() -> StatusResponse:
	"""Safe configuration status — never returns secret values."""
	supabase_url = bool((os.getenv("SUPABASE_URL") or "").strip())
	supabase_key = bool(
		(os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
		or (os.getenv("SUPABASE_ANON_KEY") or "").strip()
	)
	return StatusResponse(
		app=os.getenv("APP_NAME", "PaperFlow AI"),
		version=os.getenv("APP_VERSION", "0.1.0"),
		supabase_url_configured=supabase_url,
		supabase_key_configured=supabase_key,
	)


app.include_router(api_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(connectors_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
	_request: Request, _exception: RequestValidationError
) -> JSONResponse:
	return JSONResponse(status_code=422, content={"detail": "Invalid request"})


@app.exception_handler(Exception)
async def unhandled_exception_handler(
	_request: Request, exception: Exception
) -> JSONResponse:
	logger.exception("Unhandled application error: %s", exception)
	return JSONResponse(status_code=500, content={"detail": "Internal server error"})
