"""FastAPI application foundation for PaperFlow AI."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import os
from pathlib import Path


from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from routes.auth import router as auth_router
from routes.chat import router as chat_router
from routes.connectors import router as connectors_router
from routes.documents import router as documents_router


logger = logging.getLogger("paperflow")

_backend_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_backend_env_path, override=False)

_REQUIRED_BUCKET = "paperflow-documents"


def get_supabase_runtime_status() -> dict[str, str | bool]:
	"""Return a secret-safe runtime summary of Supabase configuration."""
	bucket_name = (os.getenv("SUPABASE_STORAGE_BUCKET") or _REQUIRED_BUCKET).strip() or _REQUIRED_BUCKET
	if bucket_name != _REQUIRED_BUCKET:
		os.environ["SUPABASE_STORAGE_BUCKET"] = _REQUIRED_BUCKET
		bucket_name = _REQUIRED_BUCKET
	return {
		"bucket_name": bucket_name,
		"bucket_configured": bucket_name == _REQUIRED_BUCKET,
		"url_configured": bool((os.getenv("SUPABASE_URL") or "").strip()),
		"anon_key_configured": bool((os.getenv("SUPABASE_ANON_KEY") or "").strip()),
		"service_role_key_configured": bool((os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()),
	}


get_supabase_runtime_status()

# Local development default when CORS_ORIGINS / FRONTEND_URL are unset.
# Production must set CORS_ORIGINS explicitly (comma-separated frontend origins).
_DEFAULT_DEV_ORIGIN = "http://localhost:5173"
_DEFAULT_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
_DEFAULT_HEADERS = ["Content-Type", "Authorization", "Accept"]


def _configured_origins() -> list[str]:
	"""Resolve allowed CORS origins from environment settings."""
	raw = (os.getenv("CORS_ORIGINS") or "").strip()
	if raw:
		origins: list[str] = []
		for origin in raw.split(","):
			candidate = origin.strip().rstrip("/")
			if candidate and candidate not in origins:
				origins.append(candidate)
		return origins

	frontend = (os.getenv("FRONTEND_URL") or _DEFAULT_DEV_ORIGIN).strip()
	if not frontend:
		return [_DEFAULT_DEV_ORIGIN]

	base = frontend.rstrip("/")
	parsed = urlsplit(base)
	host = (parsed.hostname or "").lower()
	if host in {"localhost", "127.0.0.1"}:
		fallback = base.replace(
			host,
			"127.0.0.1" if host == "localhost" else "localhost"
		)
		return [base, fallback] if base != fallback else [base]
	return [base]


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
# CORS - frontend runs on Vite port 5175
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
	supabase_bucket_configured: bool


@api_router.get("/api/status", response_model=StatusResponse)
async def status() -> StatusResponse:
	"""Safe configuration status — never returns secret values."""
	diag = get_supabase_runtime_status()
	return StatusResponse(
		app=os.getenv("APP_NAME", "PaperFlow AI"),
		version=os.getenv("APP_VERSION", "0.1.0"),
		supabase_url_configured=bool(diag["url_configured"]),
		supabase_key_configured=bool(
			diag["anon_key_configured"] or diag["service_role_key_configured"]
		),
		supabase_bucket_configured=bool(diag["bucket_configured"]),
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